"""Tests for tilepacker.core.imageops."""

from __future__ import annotations

import pytest
from PIL import Image

from tilepacker.core import imageops

from .conftest import make_tile


# --- parse_resample / ensure_rgba ------------------------------------------
def test_parse_resample_known_and_unknown():
    assert imageops.parse_resample("nearest") == Image.Resampling.NEAREST
    assert imageops.parse_resample("LANCZOS") == Image.Resampling.LANCZOS
    with pytest.raises(ValueError):
        imageops.parse_resample("bogus")


def test_ensure_rgba_converts_and_copies():
    src = Image.new("RGB", (4, 4), (1, 2, 3))
    out = imageops.ensure_rgba(src)
    assert out.mode == "RGBA"
    # even if already RGBA, a copy is returned (original is not modified).
    rgba = Image.new("RGBA", (4, 4), (1, 2, 3, 4))
    cp = imageops.ensure_rgba(rgba)
    assert cp is not rgba and cp.mode == "RGBA"


# --- resize_image: all 5 modes produce the exact target size ---------------
@pytest.mark.parametrize("mode", ["none", "stretch", "fit", "cover", "crop"])
@pytest.mark.parametrize("src_size", [(10, 10), (40, 20), (5, 60)])
def test_resize_image_exact_size(mode, src_size):
    src = make_tile((100, 150, 200, 255), src_size)
    out = imageops.resize_image(src, (32, 32), mode=mode, resample="nearest")
    assert out.size == (32, 32)
    assert out.mode == "RGBA"


def test_resize_image_stretch_fills_solid():
    src = make_tile((10, 20, 30, 255), (8, 8))
    out = imageops.resize_image(src, (16, 16), mode="stretch")
    # stretching a solid color keeps every pixel identical.
    assert out.getpixel((0, 0)) == (10, 20, 30, 255)
    assert out.getpixel((15, 15)) == (10, 20, 30, 255)


def test_resize_image_fit_pads_transparent():
    # fitting a wide input into a square cell leaves transparent top/bottom margins.
    src = make_tile((255, 0, 0, 255), (40, 10))
    out = imageops.resize_image(src, (32, 32), mode="fit", pad_color=None)
    assert out.size == (32, 32)
    assert out.getpixel((0, 0))[3] == 0  # top corner is transparent padding.


def test_resize_image_invalid_mode():
    src = make_tile((0, 0, 0, 255), (8, 8))
    with pytest.raises(ValueError):
        imageops.resize_image(src, (8, 8), mode="bogus")


# --- remove_background: corner color made transparent + flood preserves interior ---
def test_remove_background_global_makes_corner_color_transparent():
    # red border + blue interior.
    img = make_tile((255, 0, 0, 255), (8, 8))
    px = img.load()
    for y in range(2, 6):
        for x in range(2, 6):
            px[x, y] = (0, 0, 255, 255)
    out = imageops.remove_background(img, (255, 0, 0, 255), 0, flood=False)
    # the corner (background color) is transparent.
    assert out.getpixel((0, 0))[3] == 0
    # the interior blue is preserved.
    assert out.getpixel((3, 3)) == (0, 0, 255, 255)


def test_remove_background_auto_samples_corner():
    # when color=None, the most common corner color is auto-detected.
    img = make_tile((123, 45, 67, 255), (6, 6))
    out = imageops.remove_background(img, None, 0, flood=False)
    assert out.getpixel((0, 0))[3] == 0
    assert out.getpixel((5, 5))[3] == 0


def test_remove_background_flood_preserves_enclosed_interior():
    # 5x5: red on the outside, a center red pixel surrounded by a blue wall.
    #   R R R R R
    #   R B B B R
    #   R B R B R
    #   R B B B R
    #   R R R R R
    red = (255, 0, 0, 255)
    blue = (0, 0, 255, 255)
    img = make_tile(red, (5, 5))
    px = img.load()
    for (x, y) in [
        (1, 1), (2, 1), (3, 1),
        (1, 2), (3, 2),
        (1, 3), (2, 3), (3, 3),
    ]:
        px[x, y] = blue
    out_flood = imageops.remove_background(img, red, 0, flood=True)
    # the outer red border is connected from the corner and made transparent.
    assert out_flood.getpixel((0, 0))[3] == 0
    assert out_flood.getpixel((4, 4))[3] == 0
    # the center red trapped by the blue wall is preserved (alpha kept).
    assert out_flood.getpixel((2, 2)) == red

    # for comparison: with global matching, the center red is made transparent too.
    out_global = imageops.remove_background(img, red, 0, flood=False)
    assert out_global.getpixel((2, 2))[3] == 0


def test_remove_background_does_not_mutate_original():
    img = make_tile((255, 0, 0, 255), (4, 4))
    before = img.getpixel((0, 0))
    imageops.remove_background(img, (255, 0, 0, 255), 0)
    assert img.getpixel((0, 0)) == before


# --- is_empty / autocrop_bbox / trim ---------------------------------------
def test_is_empty_true_false():
    empty = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    assert imageops.is_empty(empty) is True
    solid = make_tile((255, 255, 255, 255), (8, 8))
    assert imageops.is_empty(solid) is False


def test_autocrop_bbox():
    img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    px = img.load()
    for y in range(2, 6):
        for x in range(2, 6):
            px[x, y] = (255, 255, 255, 255)
    assert imageops.autocrop_bbox(img) == (2, 2, 6, 6)
    # a fully empty image returns None.
    assert imageops.autocrop_bbox(Image.new("RGBA", (4, 4), (0, 0, 0, 0))) is None


def test_trim_removes_transparent_border():
    img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    px = img.load()
    for y in range(2, 6):
        for x in range(2, 6):
            px[x, y] = (255, 255, 255, 255)
    trimmed = imageops.trim(img)
    assert trimmed.size == (4, 4)


def test_trim_color_border():
    # green content inside a red border.
    img = make_tile((255, 0, 0, 255), (8, 8))
    px = img.load()
    for y in range(2, 6):
        for x in range(2, 6):
            px[x, y] = (0, 255, 0, 255)
    trimmed = imageops.trim(img, border_color=(255, 0, 0, 255))
    assert trimmed.size == (4, 4)
    assert trimmed.getpixel((0, 0)) == (0, 255, 0, 255)


# --- extrude_edges ---------------------------------------------------------
def test_extrude_edges_size_and_corners():
    img = make_tile((255, 0, 0, 255), (4, 4))
    out = imageops.extrude_edges(img, 2)
    assert out.size == (4 + 2 * 2, 4 + 2 * 2)  # (8, 8)
    # the extruded edges are filled with the original corner color (red, since solid).
    assert out.getpixel((0, 0)) == (255, 0, 0, 255)
    assert out.getpixel((7, 7)) == (255, 0, 0, 255)
    # the center is the original.
    assert out.getpixel((3, 3)) == (255, 0, 0, 255)


def test_extrude_edges_zero_returns_same_size_copy():
    img = make_tile((1, 2, 3, 255), (4, 4))
    out = imageops.extrude_edges(img, 0)
    assert out.size == (4, 4)
    assert out is not img  # a copy.
