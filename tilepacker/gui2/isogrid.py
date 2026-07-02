"""Isometric grid geometry for the minimal (gui2) tilepacker app.

This module is deliberately Qt-free so it can be unit tested without a display.
It provides the isometric diamond-cell maths shared by the editor and the
tileset preview:

* Each cell is a diamond whose bounding box is ``cell_w`` x ``cell_h``. Cell
  centres sit on the even-parity nodes of a half-cell lattice: the lattice index
  ``(a, b)`` (with ``a + b`` even) has its centre at ``(a * hw, b * hh)`` where
  ``hw = cell_w / 2`` and ``hh = cell_h / 2``.
* ``cell_at`` maps an image point to the containing diamond's ``(a, b)`` index.
* A drag between two points selects a rectangle in *isometric tile* coordinates
  ``(i, j) = ((a + b) / 2, (a - b) / 2)`` which projects to a diamond (rotated
  square) cluster of cells on screen -- the natural "select an area" gesture on
  an isometric grid.
* ``cell_image`` cuts one diamond out of a source image, masking everything
  outside the diamond to transparent.

Dependencies: Pillow only.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

__all__ = [
    "cell_at",
    "cell_box",
    "cells_in_diamond",
    "cells_in_rect",
    "diamond_mask",
    "cell_image",
    "iso_reading_key",
]


def cell_at(x: float, y: float, cell_w: int, cell_h: int) -> Tuple[int, int]:
    """Return the diamond lattice index ``(a, b)`` containing image point ``(x, y)``.

    Working in the normalized ``(u, v) = (nx + ny, nx - ny)`` space turns each
    diamond into an axis-aligned square, so the nearest even lattice node is the
    containing diamond's centre.
    """
    hw = cell_w / 2.0
    hh = cell_h / 2.0
    if hw <= 0 or hh <= 0:
        return (0, 0)
    nx = x / hw
    ny = y / hh
    u = nx + ny
    v = nx - ny
    u0 = 2.0 * round(u / 2.0)
    v0 = 2.0 * round(v / 2.0)
    a = int(round((u0 + v0) / 2.0))
    b = int(round((u0 - v0) / 2.0))
    return (a, b)


def cell_box(
    a: int, b: int, cell_w: int, cell_h: int, img_w: int, img_h: int
) -> Optional[Tuple[int, int, int, int]]:
    """Return the ``(left, top, right, bottom)`` pixel box of diamond ``(a, b)``.

    Returns ``None`` when the diamond's bounding box does not fit fully inside
    the ``img_w`` x ``img_h`` image, so only whole tiles are ever picked.
    """
    hw = cell_w / 2.0
    hh = cell_h / 2.0
    cx = a * hw
    cy = b * hh
    left = cx - hw
    top = cy - hh
    right = cx + hw
    bottom = cy + hh
    if left < 0 or top < 0 or right > img_w or bottom > img_h:
        return None
    return (int(round(left)), int(round(top)), int(round(right)), int(round(bottom)))


def cells_in_diamond(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    cell_w: int,
    cell_h: int,
    img_w: int,
    img_h: int,
) -> List[Tuple[int, int]]:
    """Return the whole diamond cells in the drag's isometric-tile rectangle.

    ``p0`` and ``p1`` are image-space points. Each is mapped to a diamond index
    ``(a, b)`` then to isometric tile coords ``(i, j)``; the rectangle spanning
    them in ``(i, j)`` space is a diamond cluster on screen. The result is
    returned in natural reading order (top-left to bottom-right).
    """
    a0, b0 = cell_at(p0[0], p0[1], cell_w, cell_h)
    a1, b1 = cell_at(p1[0], p1[1], cell_w, cell_h)
    i0, j0 = (a0 + b0) // 2, (a0 - b0) // 2
    i1, j1 = (a1 + b1) // 2, (a1 - b1) // 2
    ilo, ihi = min(i0, i1), max(i0, i1)
    jlo, jhi = min(j0, j1), max(j0, j1)
    out: List[Tuple[int, int]] = []
    for i in range(ilo, ihi + 1):
        for j in range(jlo, jhi + 1):
            a = i + j
            b = i - j
            if cell_box(a, b, cell_w, cell_h, img_w, img_h) is not None:
                out.append((a, b))
    out.sort(key=lambda c: iso_reading_key(*c))
    return out


def cells_in_rect(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    cell_w: int,
    cell_h: int,
    img_w: int,
    img_h: int,
) -> List[Tuple[int, int]]:
    """Return the whole diamond cells whose centre lies in the screen rectangle.

    ``p0`` and ``p1`` are image-space points. This selects every whole cell
    whose centre falls inside the axis-aligned rectangle they span -- a
    screen-aligned (square/rectangular) selection over the diamond grid, as
    opposed to :func:`cells_in_diamond`'s rotated-square (diamond) selection.
    Returned in natural reading order (top-left to bottom-right).
    """
    hw = cell_w / 2.0
    hh = cell_h / 2.0
    if hw <= 0 or hh <= 0:
        return []
    lo_x, hi_x = min(p0[0], p1[0]), max(p0[0], p1[0])
    lo_y, hi_y = min(p0[1], p1[1]), max(p0[1], p1[1])
    a_lo = int(lo_x / hw) - 1
    a_hi = int(hi_x / hw) + 1
    b_lo = int(lo_y / hh) - 1
    b_hi = int(hi_y / hh) + 1
    out: List[Tuple[int, int]] = []
    for a in range(a_lo, a_hi + 1):
        for b in range(b_lo, b_hi + 1):
            if (a + b) % 2 != 0:
                continue
            cx, cy = a * hw, b * hh
            if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y:
                if cell_box(a, b, cell_w, cell_h, img_w, img_h) is not None:
                    out.append((a, b))
    out.sort(key=lambda c: iso_reading_key(*c))
    return out


def iso_reading_key(a: int, b: int) -> Tuple[int, int]:
    """Return the natural reading-order sort key for diamond index ``(a, b)``.

    Isometric tile coords are ``x = (a + b) / 2`` (down-right axis) and
    ``y = (b - a) / 2`` (down-left axis); sorting row-major ``(y, x)`` walks the
    diamond top-left to bottom-right, matching how the preview lays tiles out.
    """
    return ((b - a) // 2, (a + b) // 2)


def diamond_mask(cell_w: int, cell_h: int) -> Image.Image:
    """Return an ``L`` mask (255 inside, 0 outside) for a ``cell_w`` x ``cell_h`` diamond."""
    mask = Image.new("L", (cell_w, cell_h), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(
        [
            (cell_w / 2.0, 0),
            (cell_w - 1, cell_h / 2.0),
            (cell_w / 2.0, cell_h - 1),
            (0, cell_h / 2.0),
        ],
        fill=255,
    )
    return mask


def cell_image(
    src: Image.Image, a: int, b: int, cell_w: int, cell_h: int
) -> Optional[Image.Image]:
    """Cut diamond ``(a, b)`` out of ``src`` as a ``cell_w`` x ``cell_h`` RGBA tile.

    Everything outside the diamond is transparent. Returns ``None`` when the
    diamond does not fit fully inside the source image.
    """
    box = cell_box(a, b, cell_w, cell_h, src.width, src.height)
    if box is None:
        return None
    region = src.crop(box).convert("RGBA")
    if region.size != (cell_w, cell_h):
        region = region.resize((cell_w, cell_h), Image.NEAREST)
    out = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
    out.paste(region, (0, 0), diamond_mask(cell_w, cell_h))
    return out
