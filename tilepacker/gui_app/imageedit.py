"""Non-destructive per-tile image editing operations for the GUI.

Every function takes a Pillow image and returns a NEW image, leaving the input
untouched. Color adjustments preserve the alpha channel. The heavy lifting for
background removal / trimming is delegated to :mod:`tilepacker.core.imageops`.

These operations are pure (no Qt, no I/O) so they can be unit-tested directly.

Dependencies: Pillow. ``numpy`` is not required.
"""

from __future__ import annotations

from math import hypot
from typing import Optional, Tuple

from PIL import Image, ImageChops, ImageEnhance, ImageOps

from tilepacker.core import imageops
from tilepacker.core.config import RGBA

__all__ = [
    "rotate_image",
    "flip_image",
    "crop_image",
    "to_grayscale",
    "adjust_hue",
    "adjust_saturation",
    "adjust_brightness",
    "adjust_contrast",
    "remove_background",
    "trim",
    "diamond_mask",
]


def _split_rgba(img: Image.Image):
    """Return the (rgb, alpha) pair of an image, converting to RGBA first."""
    rgba = imageops.ensure_rgba(img)
    r, g, b, a = rgba.split()
    return Image.merge("RGB", (r, g, b)), a


def _merge_rgb_alpha(rgb: Image.Image, alpha: Image.Image) -> Image.Image:
    """Recombine an RGB image with a separate alpha channel into RGBA."""
    r, g, b = rgb.split()
    return Image.merge("RGBA", (r, g, b, alpha))


def rotate_image(img: Image.Image, degrees: float, *, expand: bool = True) -> Image.Image:
    """Rotate an image counter-clockwise by ``degrees`` around its center.

    Args:
        img: Input image (any mode).
        degrees: Rotation angle in degrees. ``0`` returns an RGBA copy.
        expand: If True, the output canvas grows to fit the whole rotated image;
            if False, it keeps the original size and clips the corners.

    Returns:
        A new RGBA image. Areas exposed by the rotation are fully transparent.
    """
    rgba = imageops.ensure_rgba(img)
    if degrees % 360 == 0:
        return rgba.copy()
    return rgba.rotate(
        degrees,
        resample=Image.Resampling.BICUBIC,
        expand=expand,
        fillcolor=(0, 0, 0, 0),
    )


def flip_image(img: Image.Image, *, horizontal: bool = False, vertical: bool = False) -> Image.Image:
    """Mirror an image horizontally and/or vertically.

    Args:
        img: Input image (any mode).
        horizontal: Mirror left-to-right.
        vertical: Mirror top-to-bottom.

    Returns:
        A new RGBA image.
    """
    out = imageops.ensure_rgba(img).copy()
    if horizontal:
        out = out.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if vertical:
        out = out.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return out


def crop_image(img: Image.Image, box: Tuple[int, int, int, int]) -> Image.Image:
    """Crop an image to ``box`` (left, top, right, bottom), clamped to bounds.

    Args:
        img: Input image (any mode).
        box: Crop rectangle in pixel coordinates. It is clamped to the image
            bounds; a degenerate box (zero area) returns an RGBA copy unchanged.

    Returns:
        A new RGBA image cropped to the (clamped) box.
    """
    rgba = imageops.ensure_rgba(img)
    w, h = rgba.size
    left, top, right, bottom = box
    left = max(0, min(int(left), w))
    top = max(0, min(int(top), h))
    right = max(0, min(int(right), w))
    bottom = max(0, min(int(bottom), h))
    if right <= left or bottom <= top:
        return rgba.copy()
    return rgba.crop((left, top, right, bottom))


def to_grayscale(img: Image.Image) -> Image.Image:
    """Convert an image to grayscale while preserving its alpha channel.

    Args:
        img: Input image (any mode).

    Returns:
        A new RGBA image whose RGB channels are desaturated.
    """
    rgb, alpha = _split_rgba(img)
    gray = ImageOps.grayscale(rgb).convert("RGB")
    return _merge_rgb_alpha(gray, alpha)


def adjust_hue(img: Image.Image, degrees: float) -> Image.Image:
    """Rotate the hue of an image by ``degrees`` (-180..180), preserving alpha.

    The RGB channels are converted to HSV, the hue channel is shifted (with
    wrap-around), and the result is converted back to RGB. Alpha is untouched.

    Args:
        img: Input image (any mode).
        degrees: Hue rotation in degrees. ``0`` returns an RGBA copy.

    Returns:
        A new RGBA image with the hue rotated.
    """
    rgb, alpha = _split_rgba(img)
    if degrees % 360 == 0:
        return _merge_rgb_alpha(rgb, alpha)
    shift = int(round(degrees / 360.0 * 256)) % 256
    hsv = rgb.convert("HSV")
    h, s, v = hsv.split()
    h = h.point(lambda x: (x + shift) % 256)
    shifted = Image.merge("HSV", (h, s, v)).convert("RGB")
    return _merge_rgb_alpha(shifted, alpha)


def _enhance(img: Image.Image, enhancer_cls, factor: float) -> Image.Image:
    """Apply a Pillow ImageEnhance enhancer to the RGB channels only.

    Applying ImageEnhance directly to an RGBA image also scales the alpha
    channel, which is undesirable. This helper enhances RGB and re-attaches the
    original alpha.
    """
    rgb, alpha = _split_rgba(img)
    out = enhancer_cls(rgb).enhance(factor)
    return _merge_rgb_alpha(out, alpha)


def adjust_saturation(img: Image.Image, factor: float) -> Image.Image:
    """Scale color saturation. ``1.0`` is unchanged, ``0`` is grayscale.

    Args:
        img: Input image (any mode).
        factor: Saturation multiplier (>= 0).

    Returns:
        A new RGBA image (alpha preserved).
    """
    return _enhance(img, ImageEnhance.Color, factor)


def adjust_brightness(img: Image.Image, factor: float) -> Image.Image:
    """Scale brightness. ``1.0`` is unchanged, ``0`` is black.

    Args:
        img: Input image (any mode).
        factor: Brightness multiplier (>= 0).

    Returns:
        A new RGBA image (alpha preserved).
    """
    return _enhance(img, ImageEnhance.Brightness, factor)


def adjust_contrast(img: Image.Image, factor: float) -> Image.Image:
    """Scale contrast. ``1.0`` is unchanged, ``0`` is solid gray.

    Args:
        img: Input image (any mode).
        factor: Contrast multiplier (>= 0).

    Returns:
        A new RGBA image (alpha preserved).
    """
    return _enhance(img, ImageEnhance.Contrast, factor)


def remove_background(
    img: Image.Image,
    color: Optional[RGBA] = None,
    tolerance: int = 0,
    *,
    flood: bool = False,
) -> Image.Image:
    """Remove a background color, delegating to :func:`imageops.remove_background`.

    Args:
        img: Input image (any mode).
        color: Background color to remove. If ``None``, it is auto-sampled from
            the four corners.
        tolerance: RGB euclidean distance tolerance (0..441).
        flood: If True, only the region connected to the corners is cleared.

    Returns:
        A new RGBA image with the background made transparent.
    """
    return imageops.remove_background(img, color, tolerance, flood=flood)


def trim(img: Image.Image) -> Image.Image:
    """Trim the transparent border of an image, delegating to :func:`imageops.trim`.

    Args:
        img: Input image (any mode).

    Returns:
        A new RGBA image cropped to its opaque bounding box (an unchanged copy
        if it is fully transparent).
    """
    return imageops.trim(img)


def _diamond_alpha_mask(
    width: int,
    height: int,
    cx: float,
    cy: float,
    half_w: float,
    half_h: float,
    feather: float = 1.0,
) -> Image.Image:
    """Return an ``L`` mask for a centred diamond, with a soft one-pixel edge.

    Built from the distance to the diamond edge rather than by rasterizing a
    polygon: a polygon fill decides each edge pixel all-or-nothing, which leaves
    the diagonals visibly stair-stepped.

    Antialiasing is safe here in a way it is not for grid tiles. This carves one
    diamond out of one image; nothing is meant to butt up against it, so a soft
    edge has no neighbour to conflict with. (Grid cells are the opposite case --
    see ``gui2/isogrid.py``, where the edge is shared and the cut stays hard.)
    """
    if width <= 0 or height <= 0 or half_w <= 0 or half_h <= 0:
        return Image.new("L", (max(0, width), max(0, height)), 0)
    grad = hypot(1.0 / half_w, 1.0 / half_h)
    out = bytearray(width * height)
    i = 0
    for y in range(height):
        ny = abs((y + 0.5) - cy) / half_h
        for x in range(width):
            nx = abs((x + 0.5) - cx) / half_w
            alpha = ((1.0 - (nx + ny)) / grad) / feather + 0.5
            if alpha <= 0.0:
                out[i] = 0
            elif alpha >= 1.0:
                out[i] = 255
            else:
                out[i] = int(round(alpha * 255.0))
            i += 1
    return Image.frombytes("L", (width, height), bytes(out))


def diamond_mask(img: Image.Image, ratio_w: int = 1, ratio_h: int = 1) -> Image.Image:
    """Mask an image to the largest centered diamond of a given aspect ratio.

    Builds a diamond (rhombus) whose width-to-height ratio is ``ratio_w:ratio_h``
    (the tile's cell ratio) at the largest size that fits inside the image,
    centers it, and keeps only the pixels inside the diamond - everything outside
    is made fully transparent. This is the classic way to carve an isometric tile
    out of a square sprite.

    The existing alpha channel is preserved inside the diamond (already
    transparent pixels stay transparent); only the area outside the diamond is
    cleared.

    Args:
        img: Input image (any mode).
        ratio_w: Width part of the diamond aspect ratio (e.g. the tile width).
        ratio_h: Height part of the diamond aspect ratio (e.g. the tile height).

    Returns:
        A new RGBA image with the area outside the diamond made transparent.
    """
    rgba = imageops.ensure_rgba(img)
    w, h = rgba.size
    rw = max(1, int(ratio_w))
    rh = max(1, int(ratio_h))
    if w <= 0 or h <= 0:
        return rgba.copy()

    # Largest diamond of aspect ratio rw:rh inscribed in the w x h image.
    diamond_w = min(float(w), h * rw / rh)
    diamond_h = diamond_w * rh / rw
    cx, cy = w / 2.0, h / 2.0
    points = [
        (cx, cy - diamond_h / 2.0),   # top
        (cx + diamond_w / 2.0, cy),   # right
        (cx, cy + diamond_h / 2.0),   # bottom
        (cx - diamond_w / 2.0, cy),   # left
    ]

    mask = _diamond_alpha_mask(w, h, cx, cy, diamond_w / 2.0, diamond_h / 2.0)
    r, g, b, a = rgba.split()
    a = ImageChops.multiply(a, mask)
    return Image.merge("RGBA", (r, g, b, a))
