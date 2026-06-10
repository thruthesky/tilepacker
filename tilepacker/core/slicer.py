"""Spritesheet grid slicer.

Slices a large spritesheet (an image laying out many tiles in a single sheet)
into uniform grid cells to produce a list of individual tile images. Supports
``margin`` / ``spacing`` / ``offset`` and skips partial cells that fall outside
the bounds.

This module intentionally does not depend on ``config`` / ``imageops``. It uses
only pure Pillow and the standard library, so it can be reused independently of
the rest of the pipeline.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PIL import Image

__all__ = [
    "grid_dimensions",
    "slice_image",
    "slice_sheet",
]


def grid_dimensions(
    image_size: Tuple[int, int],
    tile_width: int,
    tile_height: int,
    *,
    margin: int = 0,
    spacing: int = 0,
    offset: Tuple[int, int] = (0, 0),
) -> Tuple[int, int]:
    """Compute the grid cell count ``(cols, rows)`` that fits in the given image size.

    Args:
        image_size: The image pixel size as ``(width, height)``.
        tile_width: The width of a single cell (px). Must be positive.
        tile_height: The height of a single cell (px). Must be positive.
        margin: The padding (px) from the outer image border to the start of the grid.
        spacing: The gap (px) between adjacent cells.
        offset: ``(offset_x, offset_y)`` the extra start offset (px) to skip after margin.

    Returns:
        ``(cols, rows)``. If not even one cell fits, that axis becomes 0.

    Formula:
        usable = (image edge length) - 2*margin - offset
        count  = (usable + spacing) // (tile_size + spacing)   (0 if negative)
    """
    if tile_width <= 0 or tile_height <= 0:
        raise ValueError("tile_width/tile_height must be positive.")

    width, height = image_size
    offset_x, offset_y = offset

    usable_w = width - 2 * margin - offset_x
    usable_h = height - 2 * margin - offset_y

    cols = (usable_w + spacing) // (tile_width + spacing)
    rows = (usable_h + spacing) // (tile_height + spacing)

    if cols < 0:
        cols = 0
    if rows < 0:
        rows = 0

    return (int(cols), int(rows))


def slice_image(
    img: Image.Image,
    tile_width: int,
    tile_height: int,
    *,
    margin: int = 0,
    spacing: int = 0,
    offset: Tuple[int, int] = (0, 0),
    columns: Optional[int] = None,
    rows: Optional[int] = None,
    drop_empty: bool = False,
) -> List[Image.Image]:
    """Slice an image into a uniform grid and return a list of individual tile images.

    The image is processed as RGBA and the original is never mutated. The
    top-left coordinate of each cell is::

        x = margin + offset_x + col * (tile_width  + spacing)
        y = margin + offset_y + row * (tile_height + spacing)

    Args:
        img: The source image to slice (any mode; converted to RGBA internally).
        tile_width: The cell width (px).
        tile_height: The cell height (px).
        margin: The outer image border padding (px).
        spacing: The gap between cells (px).
        offset: ``(offset_x, offset_y)`` the extra start offset (px).
        columns: The number of horizontal cells. If ``None``, computed automatically
            via :func:`grid_dimensions`.
        rows: The number of vertical cells. If ``None``, computed automatically
            via :func:`grid_dimensions`.
        drop_empty: If ``True``, exclude fully transparent tiles (``getbbox() is None``).

    Returns:
        A list of tile images in row-major (left to right, top to bottom) order.
        Partial cells that fall outside the image bounds are not included in the result.
    """
    if tile_width <= 0 or tile_height <= 0:
        raise ValueError("tile_width/tile_height must be positive.")

    # Preserve the original: convert always returns a new image, so this is safe.
    src = img if img.mode == "RGBA" else img.convert("RGBA")

    auto_cols, auto_rows = grid_dimensions(
        src.size,
        tile_width,
        tile_height,
        margin=margin,
        spacing=spacing,
        offset=offset,
    )
    n_cols = auto_cols if columns is None else columns
    n_rows = auto_rows if rows is None else rows
    if n_cols < 0:
        n_cols = 0
    if n_rows < 0:
        n_rows = 0

    offset_x, offset_y = offset
    img_w, img_h = src.size
    step_x = tile_width + spacing
    step_y = tile_height + spacing

    tiles: List[Image.Image] = []
    for row in range(n_rows):
        y = margin + offset_y + row * step_y
        if y < 0 or y + tile_height > img_h:
            # Skip the entire row that runs off vertically.
            continue
        for col in range(n_cols):
            x = margin + offset_x + col * step_x
            if x < 0 or x + tile_width > img_w:
                # Skip the partial cell that runs off horizontally.
                continue
            cell = src.crop((x, y, x + tile_width, y + tile_height))
            if drop_empty and cell.getbbox() is None:
                continue
            tiles.append(cell)

    return tiles


def slice_sheet(
    path,
    tile_width: int,
    tile_height: int,
    **kwargs,
) -> List[Image.Image]:
    """Load the spritesheet at the file path as RGBA, then slice it via :func:`slice_image`.

    Args:
        path: The image file path (``str`` or ``os.PathLike``).
        tile_width: The cell width (px).
        tile_height: The cell height (px).
        **kwargs: Keyword arguments passed through to :func:`slice_image`
            (``margin`` / ``spacing`` / ``offset`` / ``columns`` / ``rows`` /
            ``drop_empty``).

    Returns:
        A list of tile images in row-major order.
    """
    with Image.open(path) as opened:
        img = opened.convert("RGBA")
    return slice_image(img, tile_width, tile_height, **kwargs)
