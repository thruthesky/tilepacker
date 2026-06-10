"""Tests for tilepacker.core.slicer."""

from __future__ import annotations

import pytest
from PIL import Image

from tilepacker.core import slicer

from .conftest import make_tile


# --- grid_dimensions -------------------------------------------------------
def test_grid_dimensions_basic():
    assert slicer.grid_dimensions((64, 32), 32, 32) == (2, 1)
    assert slicer.grid_dimensions((96, 96), 32, 32) == (3, 3)


def test_grid_dimensions_margin_spacing():
    # margin 2, spacing 4, tile 16: usable = 100 - 4 = 96; (96+4)//(16+4)=5.
    assert slicer.grid_dimensions((100, 100), 16, 16, margin=2, spacing=4) == (5, 5)


def test_grid_dimensions_too_small_is_zero():
    assert slicer.grid_dimensions((10, 10), 32, 32) == (0, 0)


def test_grid_dimensions_bad_tile_size():
    with pytest.raises(ValueError):
        slicer.grid_dimensions((64, 64), 0, 32)


# --- slice_image -----------------------------------------------------------
def _build_sheet(cols, rows, tile=(16, 16), margin=0, spacing=0):
    """Build a simple grid sheet (each cell's top-left pixel encodes row/col)."""
    tw, th = tile
    w = 2 * margin + cols * tw + max(0, cols - 1) * spacing
    h = 2 * margin + rows * th + max(0, rows - 1) * spacing
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for r in range(rows):
        for c in range(cols):
            x = margin + c * (tw + spacing)
            y = margin + r * (th + spacing)
            for yy in range(y, y + th):
                for xx in range(x, x + tw):
                    px[xx, yy] = (10 + c, 20 + r, 30, 255)
    return img


def test_slice_image_count_and_size():
    sheet = _build_sheet(3, 2, tile=(16, 16))
    tiles = slicer.slice_image(sheet, 16, 16)
    assert len(tiles) == 6
    for t in tiles:
        assert t.size == (16, 16)


def test_slice_image_margin_spacing():
    sheet = _build_sheet(2, 2, tile=(16, 16), margin=3, spacing=5)
    tiles = slicer.slice_image(sheet, 16, 16, margin=3, spacing=5)
    assert len(tiles) == 4
    # check the top-left pixel color of the first tile (row 0, col 0).
    assert tiles[0].getpixel((0, 0)) == (10, 20, 30, 255)


def test_slice_image_skips_partial_cells():
    # width 70px (16x4=64 + 6 leftover), height 16: only 4 columns should fit.
    sheet = Image.new("RGBA", (70, 16), (0, 0, 0, 0))
    tiles = slicer.slice_image(sheet, 16, 16)
    assert len(tiles) == 4


def test_slice_image_drop_empty():
    # fill only one of the two cells.
    img = Image.new("RGBA", (32, 16), (0, 0, 0, 0))
    px = img.load()
    for y in range(16):
        for x in range(16):
            px[x, y] = (255, 0, 0, 255)  # fill only the left cell.
    all_tiles = slicer.slice_image(img, 16, 16)
    assert len(all_tiles) == 2
    dropped = slicer.slice_image(img, 16, 16, drop_empty=True)
    assert len(dropped) == 1


# --- slice_sheet (file path) ----------------------------------------------
def test_slice_sheet_from_path(tmp_path):
    sheet = _build_sheet(2, 2, tile=(16, 16))
    p = tmp_path / "sheet.png"
    sheet.save(p, "PNG")
    tiles = slicer.slice_sheet(str(p), 16, 16)
    assert len(tiles) == 4
    assert all(t.size == (16, 16) for t in tiles)
