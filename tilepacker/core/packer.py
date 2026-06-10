"""Module for compositing individual tile images into a single uniform-grid tileset image.

This module places normalized (resized) tiles onto a uniform grid that accounts
for ``margin`` / ``spacing`` / ``extrude``, producing a single RGBA tileset image.
It provides pure functions for computing the grid columns/rows, the canvas size,
and the placement coordinates of each tile, along with :func:`pack_tiles`, which
ties them together to perform the actual compositing.

Coordinate conventions:
  * "cell" coordinates refer to the top-left of one grid slot, including the
    extrude band.
  * "content" coordinates refer to the inside of the extrude band, i.e. the
    top-left where the actual tile pixels begin (= cell coordinate + extrude).

Dependencies: Pillow (required), numpy (optional acceleration, not used directly
by this module).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from PIL import Image

from tilepacker.core import imageops
from tilepacker.core.config import PackConfig

try:  # numpy is for optional acceleration. Not used directly here, but kept for contract-consistent patterns.
    import numpy as np  # noqa: F401

    _HAS_NUMPY = True
except Exception:  # pragma: no cover - guard for environments without numpy installed
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False

__all__ = [
    "compute_grid",
    "canvas_size",
    "tile_box",
    "PackedTileset",
    "pack_tiles",
]


def compute_grid(count: int, columns: int) -> Tuple[int, int]:
    """Compute a ``(cols, rows)`` grid from the tile count and the requested column count.

    Args:
        count: Number of tiles to place.
        columns: Desired number of columns. If ``>0``, that value is used as the
            fixed column count; if ``<=0``, it is auto-determined as
            ``ceil(sqrt(count))`` to stay close to a square layout.

    Returns:
        A ``(cols, rows)`` tuple. Returns ``(0, 0)`` if ``count == 0``.
    """
    if count <= 0:
        return (0, 0)
    if columns > 0:
        cols = columns
    else:
        cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)
    return (cols, rows)


def canvas_size(
    cols: int,
    rows: int,
    tile_width: int,
    tile_height: int,
    *,
    margin: int = 0,
    spacing: int = 0,
    extrude: int = 0,
) -> Tuple[int, int]:
    """Compute the final tileset canvas size ``(width, height)`` from the grid geometry.

    A single cell's size includes the extrude band:
    ``cell_w = tile_width + 2*extrude`` / ``cell_h = tile_height + 2*extrude``.

    Args:
        cols: Number of columns.
        rows: Number of rows.
        tile_width: Tile (content) width in px.
        tile_height: Tile (content) height in px.
        margin: Outer border margin of the tileset in px.
        spacing: Gap between adjacent cells in px.
        extrude: Width by which each tile edge is extended outward in px.

    Returns:
        A ``(width, height)`` tuple. Width is 0 if ``cols == 0``, and height is 0
        if ``rows == 0``.
    """
    cell_w = tile_width + 2 * extrude
    cell_h = tile_height + 2 * extrude

    if cols <= 0:
        width = 0
    else:
        width = 2 * margin + cols * cell_w + max(0, cols - 1) * spacing

    if rows <= 0:
        height = 0
    else:
        height = 2 * margin + rows * cell_h + max(0, rows - 1) * spacing

    return (width, height)


def tile_box(
    index: int,
    cols: int,
    tile_width: int,
    tile_height: int,
    *,
    margin: int = 0,
    spacing: int = 0,
    extrude: int = 0,
) -> Tuple[int, int]:
    """Compute the content top-left ``(x, y)`` coordinate of the tile at the given index.

    The returned coordinate is the inner edge of the extrude band (= the position
    where the actual tile pixels begin).

    Args:
        index: Zero-based tile index.
        cols: Number of grid columns (>0).
        tile_width: Tile (content) width in px.
        tile_height: Tile (content) height in px.
        margin: Outer border margin of the tileset in px.
        spacing: Gap between adjacent cells in px.
        extrude: Width by which each tile edge is extended in px.

    Returns:
        A content top-left ``(content_x, content_y)`` tuple.
    """
    col = index % cols
    row = index // cols
    step_x = tile_width + 2 * extrude + spacing
    step_y = tile_height + 2 * extrude + spacing
    cell_x = margin + col * step_x
    cell_y = margin + row * step_y
    content_x = cell_x + extrude
    content_y = cell_y + extrude
    return (content_x, content_y)


@dataclass
class PackedTileset:
    """Container holding the packing result.

    Attributes:
        image: The composited RGBA tileset image. Its size matches
            :func:`canvas_size` exactly.
        columns: Number of grid columns.
        rows: Number of grid rows.
        tile_count: Number of tiles actually placed.
        tile_width: Width of one tile (content) in px.
        tile_height: Height of one tile (content) in px.
        margin: Outer border margin in px.
        spacing: Gap between cells in px.
        extrude: Edge extension width in px.
    """

    image: Image.Image
    columns: int
    rows: int
    tile_count: int
    tile_width: int
    tile_height: int
    margin: int
    spacing: int
    extrude: int


def pack_tiles(tiles: Sequence[Image.Image], config: PackConfig) -> PackedTileset:
    """Composite a list of tile images into a single uniform-grid tileset image.

    Order of operations:
      1. Validate configuration consistency with ``config.validate()``.
      2. Determine ``(cols, rows)`` via :func:`compute_grid`.
      3. Compute the canvas size via :func:`canvas_size` and create a transparent
         RGBA canvas.
      4. Fit each tile to the cell (content) size via :func:`imageops.resize_image`.
      5. If ``config.background`` is set, fill each cell's content area with that
         color first, then alpha-composite the tile on top.
      6. If ``config.extrude > 0``, extend the normalized tile via
         :func:`imageops.extrude_edges` and composite it at the cell coordinate;
         otherwise composite it directly at the content coordinate
         (:func:`tile_box`).

    The original tile images are never mutated (copies are used when needed).

    Args:
        tiles: Sequence of tile images to place (any mode).
        config: Packing pipeline configuration.

    Returns:
        A :class:`PackedTileset` holding the composite result.
    """
    config.validate()

    tile_list: List[Image.Image] = list(tiles)
    count = len(tile_list)

    cols, rows = compute_grid(count, config.columns)

    tw = config.tile_width
    th = config.tile_height
    margin = config.margin
    spacing = config.spacing
    extrude = config.extrude

    width, height = canvas_size(
        cols,
        rows,
        tw,
        th,
        margin=margin,
        spacing=spacing,
        extrude=extrude,
    )

    # With zero tiles the canvas size becomes 0, so create a sensible minimal 1x1 transparent canvas.
    canvas_w = max(1, width)
    canvas_h = max(1, height)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    if count == 0:
        return PackedTileset(
            image=canvas,
            columns=cols,
            rows=rows,
            tile_count=0,
            tile_width=tw,
            tile_height=th,
            margin=margin,
            spacing=spacing,
            extrude=extrude,
        )

    background = config.background

    for index, tile in enumerate(tile_list):
        # 1) Normalize the tile to the cell (content) size.
        normalized = imageops.resize_image(
            tile,
            (tw, th),
            mode=config.resize_mode,
            resample=config.resample,
            pad_color=config.pad_color,
        )

        # 2) If a background color is set, fill the cell content area first, then alpha-composite the tile.
        if background is not None:
            cell = Image.new("RGBA", (tw, th), tuple(background))
            cell.alpha_composite(normalized)
            normalized = cell

        # 3) Determine the placement coordinate depending on whether extrude is applied.
        content_x, content_y = tile_box(
            index,
            cols,
            tw,
            th,
            margin=margin,
            spacing=spacing,
            extrude=extrude,
        )

        if extrude > 0:
            extruded = imageops.extrude_edges(normalized, extrude)
            # Top-left of the extruded tile = content coordinate shifted outward by extrude (= cell coordinate).
            paste_x = content_x - extrude
            paste_y = content_y - extrude
            canvas.alpha_composite(extruded, (paste_x, paste_y))
        else:
            canvas.alpha_composite(normalized, (content_x, content_y))

    return PackedTileset(
        image=canvas,
        columns=cols,
        rows=rows,
        tile_count=count,
        tile_width=tw,
        tile_height=th,
        margin=margin,
        spacing=spacing,
        extrude=extrude,
    )
