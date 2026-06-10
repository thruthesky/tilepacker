"""Orchestration module for the full packing pipeline.

Takes individual tile images (or a spritesheet) as input and performs the
following stages in order:

    file/sheet input
      -> preprocessing (background removal, trim)
      -> postprocessing (empty-tile removal, deduplication)
      -> packing (uniform-grid tileset composition)
      -> PNG save + .tsx/.tsj save

Each individual operation is delegated to the ``imageops`` / ``slicer`` /
``dedup`` / ``packer`` / ``tiled`` modules; this module's only job is to wire
them together in the right order according to the ``PackConfig`` settings.

Implementation policy:
  * All images are handled in Pillow RGBA mode.
  * The source images are never mutated (submodules use copies when needed).
  * numpy is used only as an optional accelerator in submodules; this module
    does not use it directly.

Dependencies: Pillow (required, via submodules), the standard library.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from PIL import Image

from tilepacker.core import imageops, slicer, dedup, packer, tiled
from tilepacker.core.config import PackConfig

try:  # numpy is an optional accelerator. This module never uses it directly, but keeps the same pattern by contract.
    import numpy as np  # noqa: F401

    _HAS_NUMPY = True
except Exception:  # pragma: no cover - guards against environments without numpy
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False

__all__ = [
    "ExportResult",
    "natural_sort_key",
    "preprocess_tiles",
    "finalize_tiles",
    "export_tileset",
    "pack_from_files",
    "pack_from_spritesheet",
]


@dataclass
class ExportResult:
    """Container holding the result of a tileset export.

    Attributes:
        image_path: Path of the saved tileset PNG.
        tsx_path: Path of the saved ``.tsx`` file, or ``None`` if not generated.
        tsj_path: Path of the saved ``.tsj`` file, or ``None`` if not generated.
        tile_count: Number of tiles ultimately placed in the tileset.
        columns: Number of columns in the tileset grid.
        rows: Number of rows in the tileset grid.
        width: Width of the tileset PNG in pixels.
        height: Height of the tileset PNG in pixels.
        tileset: The raw :class:`packer.PackedTileset` object from the packing step.
    """

    image_path: str
    tsx_path: Optional[str]
    tsj_path: Optional[str]
    tile_count: int
    columns: int
    rows: int
    width: int
    height: int
    tileset: packer.PackedTileset


def natural_sort_key(s) -> list:
    """Build a key for natural sorting.

    Splits the string into numeric and non-numeric runs, converting each numeric
    run to an integer. This makes ``"tile2"`` sort before ``"tile10"`` (the order
    a human expects). Non-numeric runs are normalized to lowercase so the
    comparison is case-insensitive.

    Args:
        s: The value to build a sort key for (usually a file path string). It is
            converted to ``str`` before processing.

    Returns:
        A comparison key of the form ``list[int | str]``, alternating integers
        and strings.
    """
    text = str(s)
    parts = re.split(r"(\d+)", text)
    key: list = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part.lower())
    return key


def preprocess_tiles(
    tiles: Sequence[Image.Image],
    config: PackConfig,
) -> List[Image.Image]:
    """Apply background-removal / trim preprocessing to each tile.

    The order applied is (1) background removal -> (2) trim. Resizing is the
    responsibility of the packing stage (:func:`packer.pack_tiles`), so it is not
    done here. The source tile images are never mutated, since the underlying
    ``imageops`` functions always return a new image.

    Args:
        tiles: List of input tile images.
        config: Pipeline configuration. The ``bg_remove`` / ``bg_color`` /
            ``bg_tolerance`` / ``bg_flood`` / ``trim`` fields are consulted.

    Returns:
        A new list of preprocessed tile images (same count and order as the input).
    """
    result: List[Image.Image] = []
    for tile in tiles:
        t = tile
        if config.bg_remove:
            t = imageops.remove_background(
                t,
                config.bg_color,
                config.bg_tolerance,
                flood=config.bg_flood,
            )
        if config.trim:
            t = imageops.trim(t)
        if t is tile:
            # If no preprocessing was applied at all, make a copy to preserve the original.
            t = imageops.ensure_rgba(t)
        result.append(t)
    return result


def finalize_tiles(
    tiles: Sequence[Image.Image],
    config: PackConfig,
) -> List[Image.Image]:
    """Apply empty-tile removal / deduplication postprocessing.

    The order applied is (1) ``drop_empty`` -> (2) ``deduplicate``. Both
    underlying functions return a tuple of the form ``(tiles, index_map)``, so
    here we keep only the remaining tile list.

    Args:
        tiles: List of input tile images.
        config: Pipeline configuration. The ``drop_empty`` / ``deduplicate``
            fields are consulted.

    Returns:
        The list of tile images after postprocessing.
    """
    result: List[Image.Image] = list(tiles)
    if config.drop_empty:
        result, _ = dedup.drop_empty_tiles(result)
    if config.deduplicate:
        result, _ = dedup.deduplicate(result)
    return result


def export_tileset(
    tiles: Sequence[Image.Image],
    config: PackConfig,
    out_path,
    *,
    write_tsx: bool = True,
    write_tsj: bool = False,
    grid_orientation: Optional[str] = None,
    grid_width: int = 0,
    grid_height: int = 0,
) -> ExportResult:
    """Preprocess/postprocess/pack a tile list, then save the PNG and definition files.

    Order of operations:
      1. Create the parent directory of ``out_path``.
      2. Process tiles via :func:`preprocess_tiles` -> :func:`finalize_tiles`.
      3. Compose the tileset image via :func:`packer.pack_tiles`.
      4. Save the composed image to ``out_path`` (as PNG).
      5. If ``write_tsx``, save a ``.tsx`` with the same stem; if ``write_tsj``,
         save a ``.tsj``. The definition file's ``image_source`` is the basename
         (relative path) of the PNG file.

    Args:
        tiles: List of input tile images.
        config: Pipeline configuration.
        out_path: Path of the tileset PNG to save.
        write_tsx: Whether to generate a ``.tsx`` definition file.
        write_tsj: Whether to generate a ``.tsj`` definition file.

    Returns:
        An :class:`ExportResult` holding the save result.
    """
    out_path = os.fspath(out_path)
    # If there is no extension, automatically append .png (so external tools such
    # as Tiled can infer the image type from the filename). The content is always
    # saved as PNG.
    if os.path.splitext(out_path)[1] == "":
        out_path = out_path + ".png"
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # 1) preprocess -> postprocess.
    processed = preprocess_tiles(tiles, config)
    finalized = finalize_tiles(processed, config)

    # 2) pack.
    tileset = packer.pack_tiles(finalized, config)

    # 3) save PNG.
    tileset.image.save(out_path, "PNG")

    image_width, image_height = tileset.image.size
    image_basename = os.path.basename(out_path)
    stem, _ = os.path.splitext(out_path)

    # 4) save definition files.
    tsx_path: Optional[str] = None
    tsj_path: Optional[str] = None

    # Tiled is unaware of extrude (tile-edge expansion, preventTearing). The
    # definition file therefore records margin/spacing corrected to match the
    # actual PNG content coordinates exactly. packer places content at
    # (margin+extrude) and lays out tiles at a stride of (tile + 2*extrude +
    # spacing), so to line up with Tiled's position formula
    # margin + col*(tilewidth + spacing) we must correct as follows:
    #   effective_margin  = margin + extrude
    #   effective_spacing = spacing + 2*extrude
    e = tileset.extrude
    meta = dict(
        name=config.name,
        image_source=image_basename,
        image_width=image_width,
        image_height=image_height,
        tile_width=tileset.tile_width,
        tile_height=tileset.tile_height,
        tile_count=tileset.tile_count,
        columns=tileset.columns,
        margin=tileset.margin + e,
        spacing=tileset.spacing + 2 * e,
    )
    # Optional grid orientation (e.g. isometric tilesets). Omitted when unset so
    # the default (orthogonal) behavior and output are unchanged.
    if grid_orientation:
        meta["grid_orientation"] = grid_orientation
        meta["grid_width"] = int(grid_width)
        meta["grid_height"] = int(grid_height)

    if write_tsx:
        tsx_path = stem + ".tsx"
        tiled.write_tsx(tsx_path, **meta)
    if write_tsj:
        tsj_path = stem + ".tsj"
        tiled.write_tsj(tsj_path, **meta)

    return ExportResult(
        image_path=out_path,
        tsx_path=tsx_path,
        tsj_path=tsj_path,
        tile_count=tileset.tile_count,
        columns=tileset.columns,
        rows=tileset.rows,
        width=image_width,
        height=image_height,
        tileset=tileset,
    )


def pack_from_files(
    paths: Sequence,
    config: PackConfig,
    out_path,
    *,
    write_tsx: bool = True,
    write_tsj: bool = False,
) -> ExportResult:
    """Load tiles from a list of file paths and export them as a tileset.

    The input paths are sorted according to the ``config.sort`` value.

      * ``"name"``    : lexicographic sort of the file paths.
      * ``"natural"`` : natural sort based on :func:`natural_sort_key` (tile2 < tile10).
      * ``"none"``    : keep input order (default).

    Args:
        paths: List of tile image file paths.
        config: Pipeline configuration.
        out_path: Path of the tileset PNG to save.
        write_tsx: Whether to generate a ``.tsx`` definition file.
        write_tsj: Whether to generate a ``.tsj`` definition file.

    Returns:
        An :class:`ExportResult` holding the save result.
    """
    ordered = list(paths)
    if config.sort == "name":
        ordered.sort(key=lambda p: str(p))
    elif config.sort == "natural":
        ordered.sort(key=natural_sort_key)
    # "none" keeps the input order.

    tiles = [imageops.load_image(p) for p in ordered]
    return export_tileset(
        tiles,
        config,
        out_path,
        write_tsx=write_tsx,
        write_tsj=write_tsj,
    )


def pack_from_spritesheet(
    sheet_path,
    config: PackConfig,
    out_path,
    *,
    sheet_margin: int = 0,
    sheet_spacing: int = 0,
    sheet_offset=(0, 0),
    write_tsx: bool = True,
    write_tsj: bool = False,
) -> ExportResult:
    """Slice a spritesheet into a grid, then repack and export it as a tileset.

    The input sheet is sliced using a cell size of
    ``(config.tile_width, config.tile_height)`` and the given ``sheet_margin`` /
    ``sheet_spacing`` / ``sheet_offset``. The sliced tiles are then repacked via
    :func:`export_tileset`, so config-driven postprocessing such as dedup /
    extrude / column reflow is applied during this step.

    Args:
        sheet_path: Path of the input spritesheet image.
        config: Pipeline configuration. ``tile_width`` / ``tile_height`` set the
            cell size.
        out_path: Path of the tileset PNG to save.
        sheet_margin: Outer border margin of the input sheet (px).
        sheet_spacing: Gap between cells in the input sheet (px).
        sheet_offset: The ``(offset_x, offset_y)`` start offset of the input sheet (px).
        write_tsx: Whether to generate a ``.tsx`` definition file.
        write_tsj: Whether to generate a ``.tsj`` definition file.

    Returns:
        An :class:`ExportResult` holding the save result.
    """
    tiles = slicer.slice_sheet(
        sheet_path,
        config.tile_width,
        config.tile_height,
        margin=sheet_margin,
        spacing=sheet_spacing,
        offset=tuple(sheet_offset),
    )
    return export_tileset(
        tiles,
        config,
        out_path,
        write_tsx=write_tsx,
        write_tsj=write_tsj,
    )
