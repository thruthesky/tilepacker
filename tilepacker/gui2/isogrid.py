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

The cut is what makes tiles line up, so the mask has two properties worth
stating up front. It is a *partition* of the lattice -- pixel ownership follows
the same rule as ``cell_at``, so every pixel belongs to exactly one diamond and
none is left behind -- and its edge is antialiased with a half-pixel outward
bleed, so neighbouring tiles' soft edges overlap into a fully opaque seam
instead of a translucent hairline. Rasterizing the diamond as a polygon
satisfies neither, and leaves a dotted transparent seam along every tile edge.

Dependencies: Pillow only.
"""

from __future__ import annotations

from collections import OrderedDict
from math import hypot
from typing import List, Optional, Tuple

from PIL import Image, ImageChops, ImageFilter

__all__ = [
    "cell_at",
    "cell_box",
    "cells_in_diamond",
    "cells_in_rect",
    "diamond_mask",
    "cell_image",
    "iso_reading_key",
    "DEFAULT_FEATHER",
    "DEFAULT_BLEED",
]

#: Width of the antialiased band along the diamond edge, in ``feather`` units
#: (see :func:`diamond_mask` for the exact formula). ``0`` -- the default -- is a
#: hard edge, which is the only setting that keeps the cut an exact partition.
#:
#: Antialiasing is off by default on purpose. An isometric tile edge is not a
#: free-standing outline: it is a *shared border*, and the neighbour owns the
#: pixels on the other side of it. Fading that border does not smooth the tile,
#: it hands the same pixels to two tiles at once. The stair-stepping visible on
#: a single tile is filled in exactly by its neighbours once tiles are laid out,
#: so a hard cut is what actually reads as smooth on a map. It is also what the
#: consumers expect: game renderers commonly draw tiles with nearest-neighbour
#: sampling and no antialiasing, where baked-in soft edges cannot be turned off.
DEFAULT_FEATHER = 0.0

#: How far the antialiased band reaches past the mathematical edge, in
#: ``feather`` units -- so the outward reach in pixels is ``bleed * feather``.
#:
#: Only meaningful when ``feather > 0``. Two abutting 50% edges composite to
#: ``1 - 0.5 * 0.5 = 75%`` opacity, so a soft edge with no bleed leaves a
#: translucent hairline; ``0.5`` makes neighbouring soft edges overlap into a
#: fully opaque seam. That overlap is exactly why antialiasing is not the
#: default: the overlapping band carries the *neighbouring* tile's colour into
#: this tile, which shows up as a coloured rim as soon as tiles are rearranged.
DEFAULT_BLEED = 0.5


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
    # Round the origin only, then derive the far edge from the cell size: this
    # keeps every box exactly cell_w x cell_h, so odd cell sizes never yield an
    # off-by-one crop that would have to be resampled back into shape.
    left = int(round(a * hw - hw))
    top = int(round(b * hh - hh))
    right = left + cell_w
    bottom = top + cell_h
    if left < 0 or top < 0 or right > img_w or bottom > img_h:
        return None
    return (left, top, right, bottom)


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


#: Memory ceiling for the mask cache, in bytes. Masks are one byte per pixel
#: and the GUI allows cells up to 4096 on a side, so a single mask can be 16 MiB
#: -- a cache bounded by entry *count* could hold a gigabyte of them. Bounding
#: by size keeps small cells (the common case) cached deeply while stopping a
#: few huge ones from pinning memory.
_MASK_CACHE_BUDGET = 32 * 1024 * 1024

#: Least-recently-used mask cache: key -> raw ``L`` bytes.
_mask_cache: "OrderedDict[tuple, bytes]" = OrderedDict()


def _cached_diamond_alpha(
    cell_w: int,
    cell_h: int,
    feather: float,
    bleed: float,
    phase_x: float,
    phase_y: float,
) -> bytes:
    """Return :func:`_diamond_alpha`'s result, cached within a byte budget."""
    key = (cell_w, cell_h, feather, bleed, phase_x, phase_y)
    hit = _mask_cache.get(key)
    if hit is not None:
        _mask_cache.move_to_end(key)
        return hit
    data = _diamond_alpha(cell_w, cell_h, feather, bleed, phase_x, phase_y)
    # Never cache a mask that cannot fit; just hand it back.
    if len(data) <= _MASK_CACHE_BUDGET:
        _mask_cache[key] = data
        used = sum(len(value) for value in _mask_cache.values())
        while used > _MASK_CACHE_BUDGET and len(_mask_cache) > 1:
            _, evicted = _mask_cache.popitem(last=False)
            used -= len(evicted)
    return data


def _diamond_alpha(
    cell_w: int,
    cell_h: int,
    feather: float,
    bleed: float,
    phase_x: float = 0.0,
    phase_y: float = 0.0,
) -> bytes:
    """Return the raw ``L`` bytes of the diamond mask.

    The mask is built from the *signed distance* to the diamond edge rather
    than by rasterizing a polygon, because the cut has to satisfy two
    properties a polygon fill does not:

    1. **It must tile the plane exactly.** Pixel ownership is decided by the
       same rule as :func:`cell_at` -- a pixel belongs to the diamond that
       contains its centre -- so every pixel is claimed by exactly one cell of
       the lattice. A polygon fill leaves unclaimed pixels along the edges,
       which show up as a dotted transparent seam once tiles are laid side by
       side.
    2. **The soft edge must overlap its neighbour.** See :data:`DEFAULT_BLEED`.

    For even cell sizes the pattern is independent of ``(a, b)``: cell centres
    sit at integer multiples of ``(hw, hh)`` and ``a + b`` is even, so the edge
    always lands at the same sub-pixel phase and one mask serves every cell.
    Odd cell sizes put ``hw``/``hh`` on a half-pixel, so the rounded crop origin
    sits half a pixel to one side or the other depending on the cell -- hence
    ``phase_x``/``phase_y``, which shift the diamond centre by that amount.
    They are part of the cache key, so cells with different phases get
    different masks instead of silently sharing a misaligned one.
    """
    hw = cell_w / 2.0 + phase_x
    hh_centre = cell_h / 2.0 + phase_y
    hw_half = cell_w / 2.0
    hh = cell_h / 2.0
    if hw <= 0.0 or hh <= 0.0:
        return bytes(max(0, cell_w) * max(0, cell_h))
    # |dx|/hw + |dy|/hh runs 0.0 at the centre to 1.0 on the edge, so
    # 1 - (that) is positive inside and negative outside. Dividing by the
    # gradient magnitude rescales it from those unitless steps into pixels,
    # which is what makes `feather` mean the same width at any cell size.
    grad = hypot(1.0 / hw_half, 1.0 / hh)
    out = bytearray(cell_w * cell_h)
    i = 0
    for y in range(cell_h):
        ny = abs((y + 0.5) - hh_centre) / hh
        for x in range(cell_w):
            nx = abs((x + 0.5) - hw) / hw_half
            dist = (1.0 - (nx + ny)) / grad  # >0 inside, <0 outside, in pixels
            if feather <= 0.0:
                out[i] = 255 if dist > 0.0 else 0
            else:
                alpha = dist / feather + 0.5 + bleed
                if alpha <= 0.0:
                    out[i] = 0
                elif alpha >= 1.0:
                    out[i] = 255
                else:
                    out[i] = int(round(alpha * 255.0))
            i += 1
    return bytes(out)


def diamond_mask(
    cell_w: int,
    cell_h: int,
    feather: float = DEFAULT_FEATHER,
    bleed: float = DEFAULT_BLEED,
    phase_x: float = 0.0,
    phase_y: float = 0.0,
) -> Image.Image:
    """Return an ``L`` mask (255 inside, 0 outside) for a ``cell_w`` x ``cell_h`` diamond.

    Args:
        cell_w: Diamond bounding-box width in pixels.
        cell_h: Diamond bounding-box height in pixels.
        feather: Width of the antialiased edge band in pixels; ``0`` gives a
            hard, stair-stepped edge.
        bleed: How far the antialiased band reaches past the mathematical edge,
            in ``feather`` units (see :data:`DEFAULT_BLEED`). Ignored when
            ``feather`` is ``0``.
        phase_x: Sub-pixel offset of the diamond centre along x. Non-zero only
            for odd cell widths, where the crop origin rounds to one side.
        phase_y: Sub-pixel offset of the diamond centre along y.

    Returns:
        A new ``L``-mode image; the caller owns it and may modify it freely.
    """
    w = max(0, int(cell_w))
    h = max(0, int(cell_h))
    data = _cached_diamond_alpha(
        w, h, float(feather), float(bleed), float(phase_x), float(phase_y)
    )
    return Image.frombytes("L", (w, h), data)


#: How many pixels of the tile's own colour are pushed outside the diamond by
#: :func:`_bleed_edge_colour`. Two is enough for bilinear sampling (which reads
#: one neighbour) with a pixel to spare; going wider costs time and buys nothing.
_EDGE_BLEED_PASSES = 2


def _bleed_edge_colour(
    region: Image.Image, mask: Image.Image, passes: int = _EDGE_BLEED_PASSES
) -> Image.Image:
    """Push the colour inside ``mask`` outward over the pixels outside it.

    Alpha is untouched -- this only rewrites RGB where the mask is empty, so
    what the tile *shows* does not change. It changes what a renderer finds
    when it samples just past the edge.

    Each pass grows the covered area by one pixel, giving the newly covered
    pixels the average colour of their already-covered neighbours. Only the
    one-pixel ring at the current boundary is touched per pass, so the cost
    follows the diamond's perimeter rather than its area.
    """
    width, height = region.size
    if width <= 0 or height <= 0 or passes <= 0:
        return region
    pixels = list(region.getdata())
    covered = [value > 0 for value in mask.getdata()]
    if not any(covered) or all(covered):
        return region
    # Binary copy of the mask that grows one pixel per pass.
    grown_mask = mask.point(lambda value: 255 if value else 0)
    for _ in range(passes):
        expanded = grown_mask.filter(ImageFilter.MaxFilter(3))
        ring = [
            index
            for index, (outer, inner) in enumerate(
                zip(expanded.getdata(), grown_mask.getdata())
            )
            if outer and not inner
        ]
        if not ring:
            break
        for index in ring:
            y, x = divmod(index, width)
            red = green = blue = count = 0
            for dy in (-1, 0, 1):
                ny = y + dy
                if not 0 <= ny < height:
                    continue
                for dx in (-1, 0, 1):
                    nx = x + dx
                    if not 0 <= nx < width:
                        continue
                    neighbour = ny * width + nx
                    if not covered[neighbour]:
                        continue
                    nr, ng, nb, _ = pixels[neighbour]
                    red += nr
                    green += ng
                    blue += nb
                    count += 1
            if count:
                pixels[index] = (
                    red // count,
                    green // count,
                    blue // count,
                    pixels[index][3],
                )
        for index in ring:
            covered[index] = True
        grown_mask = expanded
    out = Image.new("RGBA", (width, height))
    out.putdata(pixels)
    return out


def cell_image(
    src: Image.Image,
    a: int,
    b: int,
    cell_w: int,
    cell_h: int,
    feather: float = DEFAULT_FEATHER,
    bleed: float = DEFAULT_BLEED,
) -> Optional[Image.Image]:
    """Cut diamond ``(a, b)`` out of ``src`` as a ``cell_w`` x ``cell_h`` RGBA tile.

    Everything outside the diamond is transparent. Returns ``None`` when the
    diamond does not fit fully inside the source image.

    Only the alpha channel is masked; the RGB channels are kept. Compositing
    the crop onto a transparent canvas instead would multiply RGB by the mask,
    dragging every partially transparent edge pixel toward black -- a dark
    fringe on the edge, and dark halos wherever the tile is later drawn with
    smoothing or mipmaps.

    The colour left outside the diamond is then replaced by the tile's own edge
    colour (:func:`_bleed_edge_colour`). The crop is a rectangle, so the corners
    outside the diamond hold whatever the *neighbouring* tiles looked like in
    the source. Those pixels are invisible on their own -- alpha is zero -- but
    a renderer that samples with smoothing, builds mipmaps, or extrudes the
    tile's border will pull them in, painting one tile's rim with another
    tile's colour. Overwriting them keeps that impossible.
    """
    box = cell_box(a, b, cell_w, cell_h, src.width, src.height)
    if box is None:
        return None
    region = src.crop(box).convert("RGBA")
    if region.size != (cell_w, cell_h):
        region = region.resize((cell_w, cell_h), Image.NEAREST)
    # Where the diamond's true centre falls inside the (integer) crop box. This
    # is zero for even cell sizes; for odd ones the box origin was rounded, so
    # the centre sits half a pixel off and the mask has to follow it.
    phase_x = a * (cell_w / 2.0) - box[0] - cell_w / 2.0
    phase_y = b * (cell_h / 2.0) - box[1] - cell_h / 2.0
    mask = diamond_mask(cell_w, cell_h, feather, bleed, phase_x, phase_y)
    region = _bleed_edge_colour(region, mask)
    red, green, blue, alpha = region.split()
    alpha = ImageChops.multiply(alpha, mask)
    return Image.merge("RGBA", (red, green, blue, alpha))
