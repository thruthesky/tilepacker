"""Low-level image operations on a single image.

Provides per-pixel operations used in the pre-/post-processing stages of the
packing pipeline, such as resizing, background removal, trimming (margin
removal), and extruding (edge replication). Every operation takes and returns a
Pillow RGBA image and never mutates the source image (it makes a copy when
needed).

When numpy is installed, some operations (such as global color matching) are
vectorized for speed, but the results are identical when running on pure Pillow
without numpy.

Dependencies: Pillow (required), numpy (optional acceleration).
"""

from __future__ import annotations

from collections import Counter, deque
from typing import Optional, Tuple

from PIL import Image

from tilepacker.core.config import RGBA

try:  # numpy is for optional acceleration; without it, the pure-Pillow path behaves identically.
    import numpy as np

    _HAS_NUMPY = True
except Exception:  # pragma: no cover - guards against environments without numpy installed
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False

__all__ = [
    "parse_resample",
    "ensure_rgba",
    "load_image",
    "resize_image",
    "remove_background",
    "trim",
    "autocrop_bbox",
    "is_empty",
    "extrude_edges",
]

#: Fully transparent color (black, alpha 0). The default fill color when pad_color is None.
_TRANSPARENT: RGBA = (0, 0, 0, 0)

#: Mapping from resample name to Pillow Resampling constant.
_RESAMPLE_MAP = {
    "nearest": Image.Resampling.NEAREST,
    "box": Image.Resampling.BOX,
    "bilinear": Image.Resampling.BILINEAR,
    "hamming": Image.Resampling.HAMMING,
    "bicubic": Image.Resampling.BICUBIC,
    "lanczos": Image.Resampling.LANCZOS,
}


def parse_resample(name: str) -> int:
    """Convert a resample filter name to Pillow's ``Image.Resampling`` constant.

    Mapping: ``nearest`` -> NEAREST, ``box`` -> BOX, ``bilinear`` -> BILINEAR,
    ``hamming`` -> HAMMING, ``bicubic`` -> BICUBIC, ``lanczos`` -> LANCZOS.
    Case is ignored.

    Args:
        name: Filter name string.

    Returns:
        Pillow's Resampling integer constant.

    Raises:
        ValueError: When the name is not supported.
    """
    key = str(name).strip().lower()
    try:
        return _RESAMPLE_MAP[key]
    except KeyError:
        raise ValueError(
            f"Unsupported resample filter: {name!r} "
            f"(allowed values: {sorted(_RESAMPLE_MAP)})"
        )


def ensure_rgba(img: Image.Image) -> Image.Image:
    """Return an RGBA copy of the image, converting it if it is not already RGBA.

    Even when the image is already RGBA, always return a copy so the caller can
    safely work with it without affecting the original (the source-is-never-mutated
    principle).

    Args:
        img: A Pillow image in any mode.

    Returns:
        A new image in RGBA mode.
    """
    if img.mode == "RGBA":
        return img.copy()
    return img.convert("RGBA")


def load_image(path) -> Image.Image:
    """Open an image from a file and return it in RGBA mode.

    Returns a copy loaded into memory via ``ensure_rgba`` so it stays safe even
    after the file handle is closed.

    Args:
        path: Image file path (str or path-like).

    Returns:
        A new image in RGBA mode.
    """
    with Image.open(path) as src:
        src.load()
        return ensure_rgba(src)


def _resolve_pad(pad_color: Optional[RGBA]) -> RGBA:
    """Normalize pad_color to the transparent color when it is None."""
    return _TRANSPARENT if pad_color is None else tuple(pad_color)  # type: ignore[return-value]


def resize_image(
    img: Image.Image,
    size: Tuple[int, int],
    *,
    mode: str = "fit",
    resample: str = "nearest",
    pad_color: Optional[RGBA] = None,
) -> Image.Image:
    """Fit the image to the given cell size, always returning RGBA at exactly ``size``.

    Args:
        img: Input image (any mode).
        size: Target size ``(width, height)``.
        mode: Resize mode. ``stretch`` / ``fit`` / ``cover`` / ``crop`` / ``none``.
        resample: Interpolation filter name (see :func:`parse_resample`).
        pad_color: Fill color for the margins. Transparent when ``None``.

    Returns:
        A new RGBA image that is exactly ``size``.

    Raises:
        ValueError: When ``mode`` is not supported.
    """
    target_w, target_h = int(size[0]), int(size[1])
    src = ensure_rgba(img)
    sw, sh = src.size
    pad = _resolve_pad(pad_color)
    flt = parse_resample(resample)

    if mode == "stretch":
        return src.resize((target_w, target_h), flt)

    if mode == "fit":
        if sw <= 0 or sh <= 0:
            return Image.new("RGBA", (target_w, target_h), pad)
        scale = min(target_w / sw, target_h / sh)
        nw = max(1, round(sw * scale))
        nh = max(1, round(sh * scale))
        resized = src.resize((nw, nh), flt)
        canvas = Image.new("RGBA", (target_w, target_h), pad)
        ox = (target_w - nw) // 2
        oy = (target_h - nh) // 2
        canvas.paste(resized, (ox, oy))
        return canvas

    if mode == "cover":
        if sw <= 0 or sh <= 0:
            return Image.new("RGBA", (target_w, target_h), pad)
        scale = max(target_w / sw, target_h / sh)
        nw = max(1, round(sw * scale))
        nh = max(1, round(sh * scale))
        resized = src.resize((nw, nh), flt)
        # Crop the center to the target size.
        left = (nw - target_w) // 2
        top = (nh - target_h) // 2
        canvas = Image.new("RGBA", (target_w, target_h), pad)
        canvas.paste(resized, (-left, -top))
        return canvas

    if mode == "crop":
        # Without resizing, center the source and crop/pad it to size.
        canvas = Image.new("RGBA", (target_w, target_h), pad)
        ox = (target_w - sw) // 2
        oy = (target_h - sh) // 2
        canvas.paste(src, (ox, oy))
        return canvas

    if mode == "none":
        # Without resizing, align the source to the top-left and crop/pad it to size.
        canvas = Image.new("RGBA", (target_w, target_h), pad)
        canvas.paste(src, (0, 0))
        return canvas

    raise ValueError(
        f"Unsupported resize mode: {mode!r} "
        "(allowed values: stretch, fit, cover, crop, none)"
    )


def _sample_corner_bg(img: Image.Image) -> RGBA:
    """Sample the four corner pixels and estimate the most common color as the background."""
    w, h = img.size
    px = img.load()
    corners = [
        px[0, 0],
        px[w - 1, 0],
        px[0, h - 1],
        px[w - 1, h - 1],
    ]
    # remove_background only uses the background RGB, so aggregate on an RGB basis too.
    # (This prevents pixels with the same RGB but different alpha from splitting into
    # separate keys and skewing the most-common decision.)
    rgb_corners = [(c[0], c[1], c[2]) for c in corners]
    counter = Counter(rgb_corners)
    # Most common value. On a tie, the top-left wins (Counter preserves insertion order).
    r, g, b = counter.most_common(1)[0][0]
    return (r, g, b, 255)


def remove_background(
    img: Image.Image,
    color: Optional[RGBA] = None,
    tolerance: int = 0,
    *,
    flood: bool = False,
) -> Image.Image:
    """Make pixels matching the background color transparent by setting their alpha to 0.

    Args:
        img: Input image (any mode).
        color: Background color to remove. When ``None``, the most common color of
            the four corners is auto-estimated.
        tolerance: Allowed RGB Euclidean distance. When ``0``, only exactly matching
            pixels are targeted; when ``>0``, pixels within distance ≤ tolerance are
            targeted (alpha excluded).
        flood: When ``False``, target pixels are made transparent across the whole
            image. When ``True``, a 4-neighbor search is seeded from the four corners
            so only the region connected to the background is made transparent
            (same-color pixels in the interior are preserved).

    Returns:
        A new RGBA image with the background removed (the original is preserved).
    """
    out = ensure_rgba(img)
    w, h = out.size
    if w == 0 or h == 0:
        return out

    bg = _sample_corner_bg(out) if color is None else tuple(color)
    br, bg_g, bb = bg[0], bg[1], bg[2]
    tol_sq = float(tolerance) * float(tolerance)

    if not flood:
        if _HAS_NUMPY:
            arr = np.array(out)  # (h, w, 4)
            rgb = arr[:, :, :3].astype(np.int32)
            dr = rgb[:, :, 0] - br
            dg = rgb[:, :, 1] - bg_g
            db = rgb[:, :, 2] - bb
            dist_sq = dr * dr + dg * dg + db * db
            if tolerance <= 0:
                mask = dist_sq == 0
            else:
                mask = dist_sq <= tol_sq
            arr[mask, 3] = 0
            return Image.fromarray(arr, "RGBA")

        # Pure-Pillow path.
        px = out.load()
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if _matches(r, g, b, br, bg_g, bb, tolerance, tol_sq):
                    px[x, y] = (r, g, b, 0)
        return out

    # flood=True: 4-neighbor BFS seeded from the four corners.
    px = out.load()
    visited = bytearray(w * h)
    stack = deque()
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    for sx, sy in seeds:
        idx = sy * w + sx
        if visited[idx]:
            continue
        r, g, b, a = px[sx, sy]
        if _matches(r, g, b, br, bg_g, bb, tolerance, tol_sq):
            visited[idx] = 1
            stack.append((sx, sy))

    while stack:
        x, y = stack.pop()
        r, g, b, a = px[x, y]
        px[x, y] = (r, g, b, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                nidx = ny * w + nx
                if visited[nidx]:
                    continue
                nr, ng, nb, na = px[nx, ny]
                if _matches(nr, ng, nb, br, bg_g, bb, tolerance, tol_sq):
                    visited[nidx] = 1
                    stack.append((nx, ny))
    return out


def _matches(r, g, b, br, bg, bb, tolerance: int, tol_sq: float) -> bool:
    """Determine whether a single pixel matches the background color (within tolerance)."""
    if tolerance <= 0:
        return r == br and g == bg and b == bb
    dr = r - br
    dg = g - bg
    db = b - bb
    return (dr * dr + dg * dg + db * db) <= tol_sq


def autocrop_bbox(img: Image.Image) -> Optional[Tuple[int, int, int, int]]:
    """Return the bounding box of the opaque (alpha>0) region.

    Args:
        img: Input image (any mode).

    Returns:
        A ``(left, top, right, bottom)`` tuple. ``None`` if there are no opaque pixels.
    """
    rgba = ensure_rgba(img)
    alpha = rgba.getchannel("A")
    # getbbox returns the bbox of non-zero values (the alpha>0 region).
    return alpha.getbbox()


def is_empty(img: Image.Image, *, alpha_threshold: int = 0) -> bool:
    """Return ``True`` when every pixel's alpha is at or below ``alpha_threshold``.

    Args:
        img: Input image (any mode).
        alpha_threshold: Alpha at or below this value is treated as 'empty'.

    Returns:
        ``True`` if the image is (effectively) empty.
    """
    rgba = ensure_rgba(img)
    alpha = rgba.getchannel("A")
    if _HAS_NUMPY:
        return bool((np.asarray(alpha) <= alpha_threshold).all())
    extrema = alpha.getextrema()  # (min, max). None for a zero-size image.
    if extrema is None:
        # A zero-size (0x0) image is treated as empty, matching the numpy path (.all() == True).
        return True
    return extrema[1] <= alpha_threshold


def trim(
    img: Image.Image,
    *,
    border_color: Optional[RGBA] = None,
    tolerance: int = 0,
) -> Image.Image:
    """Return a copy of the image with the border margin (transparent or a given color) cropped off.

    Args:
        img: Input image (any mode).
        border_color: When ``None``, crop to the bounding box of the alpha>0 region
            (removes a transparent border). When a color is given, remove a border
            made of that color (±tolerance).
        tolerance: Allowed color distance when ``border_color`` is given.

    Returns:
        A new RGBA image with the margin removed. If there is no content at all,
        returns the source copy unchanged.
    """
    rgba = ensure_rgba(img)

    if border_color is None:
        bbox = autocrop_bbox(rgba)
        if bbox is None:
            return rgba
        return rgba.crop(bbox)

    # Remove a given-color border: use the bbox of a temporary image with that color replaced by transparency.
    bc = tuple(border_color)
    br, bg_g, bb = bc[0], bc[1], bc[2]
    tol_sq = float(tolerance) * float(tolerance)
    w, h = rgba.size
    if w == 0 or h == 0:
        return rgba

    if _HAS_NUMPY:
        arr = np.array(rgba)
        rgb = arr[:, :, :3].astype(np.int32)
        dr = rgb[:, :, 0] - br
        dg = rgb[:, :, 1] - bg_g
        db = rgb[:, :, 2] - bb
        dist_sq = dr * dr + dg * dg + db * db
        if tolerance <= 0:
            bg_mask = dist_sq == 0
        else:
            bg_mask = dist_sq <= tol_sq
        # Content mask: pixels that are not the background color.
        content = ~bg_mask
        ys, xs = np.where(content)
        if ys.size == 0:
            return rgba
        left = int(xs.min())
        top = int(ys.min())
        right = int(xs.max()) + 1
        bottom = int(ys.max()) + 1
        return rgba.crop((left, top, right, bottom))

    # Pure-Pillow path: use the bbox of an alpha mask that marks only content pixel coordinates.
    mask = Image.new("L", (w, h), 0)
    mpx = mask.load()
    spx = rgba.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = spx[x, y]
            if not _matches(r, g, b, br, bg_g, bb, tolerance, tol_sq):
                mpx[x, y] = 255
    bbox = mask.getbbox()
    if bbox is None:
        return rgba
    return rgba.crop(bbox)


def extrude_edges(img: Image.Image, amount: int) -> Image.Image:
    """Replicate the tile edges outward to expand the outline (prevents bleeding when scaling).

    Keeps the original in the center and replicates the top/bottom/left/right edge
    rows and columns outward by ``amount`` px each, filling the four corners with the
    respective corner pixel.

    Args:
        img: Input image (any mode).
        amount: Expansion width (px). When ``<=0``, returns a plain RGBA copy.

    Returns:
        A new RGBA image of size ``(w, h)`` when ``amount<=0``, otherwise
        ``(w+2*amount, h+2*amount)``.
    """
    src = ensure_rgba(img)
    if amount <= 0:
        return src

    w, h = src.size
    out_w, out_h = w + 2 * amount, h + 2 * amount
    out = Image.new("RGBA", (out_w, out_h), _TRANSPARENT)

    # 1) Place the original in the center.
    out.paste(src, (amount, amount))

    # 2) Replicate the top/bottom edge rows (horizontal strips).
    top_row = src.crop((0, 0, w, 1)).resize((w, amount), Image.Resampling.NEAREST)
    bottom_row = src.crop((0, h - 1, w, h)).resize((w, amount), Image.Resampling.NEAREST)
    out.paste(top_row, (amount, 0))
    out.paste(bottom_row, (amount, amount + h))

    # 3) Replicate the left/right edge columns (vertical strips).
    left_col = src.crop((0, 0, 1, h)).resize((amount, h), Image.Resampling.NEAREST)
    right_col = src.crop((w - 1, 0, w, h)).resize((amount, h), Image.Resampling.NEAREST)
    out.paste(left_col, (0, amount))
    out.paste(right_col, (amount + w, amount))

    # 4) Fill the four corners with the respective corner pixel.
    px = src.load()
    tl = Image.new("RGBA", (amount, amount), px[0, 0])
    tr = Image.new("RGBA", (amount, amount), px[w - 1, 0])
    bl = Image.new("RGBA", (amount, amount), px[0, h - 1])
    brr = Image.new("RGBA", (amount, amount), px[w - 1, h - 1])
    out.paste(tl, (0, 0))
    out.paste(tr, (amount + w, 0))
    out.paste(bl, (0, amount + h))
    out.paste(brr, (amount + w, amount + h))

    return out
