"""Tests for tilepacker.core.packer."""

from __future__ import annotations

import math

from tilepacker.core import packer
from tilepacker.core.config import PackConfig

from .conftest import make_tile


# --- compute_grid ----------------------------------------------------------
def test_compute_grid_fixed_columns():
    assert packer.compute_grid(5, 3) == (3, 2)
    assert packer.compute_grid(6, 3) == (3, 2)
    assert packer.compute_grid(7, 3) == (3, 3)


def test_compute_grid_auto_square():
    # when columns<=0, ceil(sqrt(count)).
    assert packer.compute_grid(4, 0) == (2, 2)
    assert packer.compute_grid(9, 0) == (3, 3)
    c = math.ceil(math.sqrt(5))
    assert packer.compute_grid(5, 0) == (c, math.ceil(5 / c))


def test_compute_grid_empty():
    assert packer.compute_grid(0, 4) == (0, 0)


# --- canvas_size -----------------------------------------------------------
def test_canvas_size_basic():
    assert packer.canvas_size(2, 2, 32, 32) == (64, 64)


def test_canvas_size_margin_spacing():
    # 2x2, tile 16, margin 2, spacing 4:
    #   width = 2*2 + 2*16 + 1*4 = 4 + 32 + 4 = 40.
    assert packer.canvas_size(2, 2, 16, 16, margin=2, spacing=4) == (40, 40)


def test_canvas_size_extrude():
    # cell = tile + 2*extrude. 2x1, tile 16, extrude 1: cell 18.
    #   width = 2*18 = 36; height = 1*18 = 18.
    assert packer.canvas_size(2, 1, 16, 16, extrude=1) == (36, 18)


def test_canvas_size_zero_dims():
    assert packer.canvas_size(0, 3, 16, 16) == (0, 48)
    assert packer.canvas_size(3, 0, 16, 16) == (48, 0)


# --- tile_box --------------------------------------------------------------
def test_tile_box_no_extras():
    # index 0 -> (0, 0); index 1 (cols=2) -> (16, 0); index 2 -> (0, 16).
    assert packer.tile_box(0, 2, 16, 16) == (0, 0)
    assert packer.tile_box(1, 2, 16, 16) == (16, 0)
    assert packer.tile_box(2, 2, 16, 16) == (0, 16)


def test_tile_box_margin_spacing_extrude():
    # cols=2, tile 16, margin 2, spacing 4, extrude 1.
    #   step = 16 + 2*1 + 4 = 22.
    #   index 0 content = margin + 0 + extrude = (3, 3).
    #   index 1 content = margin + step + extrude = 2 + 22 + 1 = 25.
    assert packer.tile_box(0, 2, 16, 16, margin=2, spacing=4, extrude=1) == (3, 3)
    assert packer.tile_box(1, 2, 16, 16, margin=2, spacing=4, extrude=1) == (25, 3)


# --- pack_tiles ------------------------------------------------------------
def test_pack_tiles_size_and_grid():
    tiles = [make_tile((i * 30, 0, 0, 255), (32, 32)) for i in range(4)]
    cfg = PackConfig(tile_width=32, tile_height=32, columns=2)
    result = packer.pack_tiles(tiles, cfg)
    assert result.columns == 2 and result.rows == 2
    assert result.tile_count == 4
    assert result.image.size == (64, 64)
    assert result.image.mode == "RGBA"


def test_pack_tiles_auto_columns():
    tiles = [make_tile((0, i * 20, 0, 255), (16, 16)) for i in range(9)]
    cfg = PackConfig(tile_width=16, tile_height=16, columns=0)
    result = packer.pack_tiles(tiles, cfg)
    assert result.columns == 3 and result.rows == 3
    assert result.image.size == (48, 48)


def test_pack_tiles_extrude_canvas():
    tiles = [make_tile((255, 0, 0, 255), (16, 16)) for _ in range(2)]
    cfg = PackConfig(tile_width=16, tile_height=16, columns=2, extrude=1)
    result = packer.pack_tiles(tiles, cfg)
    # cell = 18; width = 2*18 = 36, height = 18.
    assert result.image.size == (36, 18)
    assert result.extrude == 1


def test_pack_tiles_empty():
    cfg = PackConfig(tile_width=16, tile_height=16)
    result = packer.pack_tiles([], cfg)
    assert result.tile_count == 0
    # empty input yields a minimal 1x1 canvas.
    assert result.image.size == (1, 1)


def test_pack_tiles_places_pixels():
    # packing one solid red tile into a 32x32 cell makes the canvas center red.
    tiles = [make_tile((255, 0, 0, 255), (32, 32))]
    cfg = PackConfig(tile_width=32, tile_height=32, columns=1)
    result = packer.pack_tiles(tiles, cfg)
    assert result.image.getpixel((0, 0)) == (255, 0, 0, 255)
