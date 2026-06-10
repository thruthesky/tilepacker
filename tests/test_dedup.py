"""Tests for tilepacker.core.dedup."""

from __future__ import annotations

from PIL import Image

from tilepacker.core import dedup

from .conftest import make_tile


# --- image_signature -------------------------------------------------------
def test_image_signature_same_and_different():
    a = make_tile((255, 0, 0, 255), (8, 8))
    b = make_tile((255, 0, 0, 255), (8, 8))
    c = make_tile((0, 255, 0, 255), (8, 8))
    assert dedup.image_signature(a) == dedup.image_signature(b)
    assert dedup.image_signature(a) != dedup.image_signature(c)


def test_image_signature_size_matters():
    a = make_tile((255, 0, 0, 255), (8, 8))
    d = make_tile((255, 0, 0, 255), (16, 16))
    assert dedup.image_signature(a) != dedup.image_signature(d)


# --- deduplicate -----------------------------------------------------------
def test_deduplicate_index_map():
    red = make_tile((255, 0, 0, 255), (8, 8))
    green = make_tile((0, 255, 0, 255), (8, 8))
    blue = make_tile((0, 0, 255, 255), (8, 8))
    red2 = make_tile((255, 0, 0, 255), (8, 8))
    green2 = make_tile((0, 255, 0, 255), (8, 8))
    tiles = [red, green, blue, red2, green2]
    unique, index_map = dedup.deduplicate(tiles)
    assert len(unique) == 3
    # First-seen order: red(0), green(1), blue(2).
    assert index_map == [0, 1, 2, 0, 1]
    assert len(index_map) == len(tiles)


def test_deduplicate_all_unique():
    tiles = [make_tile((i * 40, 0, 0, 255), (8, 8)) for i in range(4)]
    unique, index_map = dedup.deduplicate(tiles)
    assert len(unique) == 4
    assert index_map == [0, 1, 2, 3]


def test_deduplicate_does_not_mutate_input():
    tiles = [make_tile((255, 0, 0, 255), (8, 8))]
    before = tiles[0].getpixel((0, 0))
    dedup.deduplicate(tiles)
    assert tiles[0].getpixel((0, 0)) == before


# --- drop_empty_tiles ------------------------------------------------------
def test_drop_empty_tiles():
    solid = make_tile((255, 0, 0, 255), (8, 8))
    empty = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    tiles = [solid, empty, solid, empty]
    kept, indices = dedup.drop_empty_tiles(tiles)
    assert len(kept) == 2
    assert indices == [0, 2]


def test_drop_empty_tiles_alpha_threshold():
    # A tile with alpha 5 counts as empty when threshold is 5 or below.
    faint = Image.new("RGBA", (8, 8), (255, 0, 0, 5))
    solid = make_tile((255, 0, 0, 255), (8, 8))
    kept, indices = dedup.drop_empty_tiles([faint, solid], alpha_threshold=5)
    assert len(kept) == 1
    assert indices == [1]


def test_drop_empty_tiles_none_empty():
    tiles = [make_tile((i * 50, 0, 0, 255), (8, 8)) for i in range(3)]
    kept, indices = dedup.drop_empty_tiles(tiles)
    assert len(kept) == 3
    assert indices == [0, 1, 2]
