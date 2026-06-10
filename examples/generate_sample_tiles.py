#!/usr/bin/env python3
"""Runnable script that generates sample tile images for the tilepacker demo.

Using only Pillow, it creates several square tile PNGs with various colors and
simple patterns (circle, square, diagonal, cross, border, etc.) and saves them
under ``examples/sample_tiles/`` (or the directory given via ``--out``).

Each tile is drawn as a pattern over a solid background (the default background
color is magenta ``#ff00ff``). Since all four corners share the same solid
color, you can directly try the "auto-sample corners" background removal demo of
``tilepacker rmbg`` / ``pack --remove-bg``.

Example usage::

    python examples/generate_sample_tiles.py --count 12 --size 32 \
        --out examples/sample_tiles

Options:
    --count   Number of tiles to generate (default 12)
    --size    Pixel size of one tile side (default 32)
    --out     Output directory (default examples/sample_tiles)
    --bg      Background (= removal target) color. '#rrggbb' / 'r,g,b' / 'none', etc. (default #ff00ff)

Dependencies: Pillow only.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

__all__ = [
    "RGBA",
    "build_palette",
    "draw_pattern",
    "generate_tiles",
    "parse_bg",
    "main",
]

#: Type alias for an RGBA color 4-tuple.
RGBA = Tuple[int, int, int, int]

#: Palette of vivid foreground colors used for patterns (opaque RGBA).
_PALETTE: Tuple[RGBA, ...] = (
    (220, 50, 47, 255),    # red
    (38, 139, 210, 255),   # blue
    (133, 153, 0, 255),    # green
    (181, 137, 0, 255),    # yellow/ochre
    (108, 113, 196, 255),  # purple
    (42, 161, 152, 255),   # teal
    (203, 75, 22, 255),    # orange
    (211, 54, 130, 255),   # pink
    (88, 110, 117, 255),   # slate
    (147, 161, 161, 255),  # light gray
    (7, 54, 66, 255),      # dark navy
    (238, 232, 213, 255),  # cream
)

#: Pattern kinds applied in a cycle.
_PATTERNS: Tuple[str, ...] = (
    "solid",     # solid fill
    "circle",    # centered circle
    "square",    # centered square
    "diagonal",  # diagonal band
    "cross",     # cross
    "border",    # border only
)


def build_palette(count: int) -> List[RGBA]:
    """Return as many foreground colors as needed, cycling the palette.

    If more tiles are requested than the built-in palette has, colors are
    cycled to fill the remainder.

    Args:
        count: Number of colors needed (number of tiles).

    Returns:
        A list of RGBA colors of length ``count``.
    """
    if count <= 0:
        return []
    return [_PALETTE[i % len(_PALETTE)] for i in range(count)]


def draw_pattern(
    size: int,
    fg: RGBA,
    bg: Optional[RGBA],
    pattern: str,
) -> Image.Image:
    """Create an RGBA tile image with the given pattern drawn over a solid background.

    Args:
        size: Pixel size of one tile side.
        fg: Pattern (foreground) color as RGBA.
        bg: Background color as RGBA. ``None`` means a fully transparent background.
        pattern: Pattern kind. One of ``_PATTERNS`` (treated as ``"solid"`` if unknown).

    Returns:
        A ``Pillow`` RGBA image of size ``size x size``.
    """
    base: RGBA = bg if bg is not None else (0, 0, 0, 0)
    img = Image.new("RGBA", (size, size), base)
    draw = ImageDraw.Draw(img)
    m = max(1, size // 8)               # margin
    lo, hi = m, size - 1 - m            # inner bounds of the pattern

    if pattern == "circle":
        draw.ellipse([lo, lo, hi, hi], fill=fg)
    elif pattern == "square":
        draw.rectangle([lo, lo, hi, hi], fill=fg)
    elif pattern == "diagonal":
        band = max(1, size // 5)
        draw.line([(0, size), (size, 0)], fill=fg, width=band)
    elif pattern == "cross":
        thick = max(1, size // 5)
        c0 = (size - thick) // 2
        c1 = c0 + thick
        draw.rectangle([c0, lo, c1, hi], fill=fg)     # vertical bar
        draw.rectangle([lo, c0, hi, c1], fill=fg)     # horizontal bar
    elif pattern == "border":
        width = max(1, size // 6)
        draw.rectangle([0, 0, size - 1, size - 1], outline=fg, width=width)
    else:  # "solid" and unspecified
        draw.rectangle([lo, lo, hi, hi], fill=fg)

    return img


def generate_tiles(
    count: int,
    size: int,
    out_dir: str,
    bg: Optional[RGBA],
) -> List[str]:
    """Generate sample tiles, save them as PNGs, and return the saved paths.

    Filenames follow the ``tile_00.png``, ``tile_01.png`` … format, and
    ``out_dir`` is created if it does not exist. Colors and patterns are
    combined by cycling the palette and pattern lists respectively.

    Args:
        count: Number of tiles to generate (positive).
        size: Pixel size of one tile side (positive).
        out_dir: Directory to save the resulting PNGs in.
        bg: Background (= removal target) color as RGBA. ``None`` means a transparent background.

    Returns:
        A list of absolute paths to the saved PNG files (in creation order).

    Raises:
        ValueError: When ``count`` or ``size`` is less than 1.
    """
    if count < 1:
        raise ValueError("count must be at least 1.")
    if size < 1:
        raise ValueError("size must be at least 1.")

    os.makedirs(out_dir, exist_ok=True)
    colors = build_palette(count)
    width = max(2, len(str(count - 1)))  # zero-pad width for filenames

    saved: List[str] = []
    for i in range(count):
        pattern = _PATTERNS[i % len(_PATTERNS)]
        img = draw_pattern(size, colors[i], bg, pattern)
        filename = f"tile_{i:0{width}d}.png"
        path = os.path.abspath(os.path.join(out_dir, filename))
        img.save(path, "PNG")
        saved.append(path)
    return saved


def parse_bg(value: Optional[str]) -> Optional[RGBA]:
    """Parse the ``--bg`` option string into an RGBA tuple (``None`` for transparent).

    Accepted formats:
      * ``None`` / ``""`` / ``"none"`` / ``"transparent"`` -> ``None`` (transparent background)
      * ``"#rgb"`` / ``"#rrggbb"`` / ``"#rrggbbaa"`` hexadecimal
      * ``"r,g,b"`` / ``"r,g,b,a"`` comma-separated

    Args:
        value: The color string given by the user, or ``None``.

    Returns:
        An RGBA 4-tuple, or ``None``.

    Raises:
        ValueError: When the format cannot be parsed.
    """
    if value is None:
        return None
    s = value.strip().lower()
    if s in ("", "none", "transparent"):
        return None
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            r, g, b = (int(ch * 2, 16) for ch in h)
            return (r, g, b, 255)
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
        if len(h) == 8:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
        raise ValueError(f"hex color must be in #rgb/#rrggbb/#rrggbbaa format: {value!r}")
    if "," in s:
        parts = [int(p) for p in s.split(",")]
        if len(parts) == 3:
            parts.append(255)
        if len(parts) != 4:
            raise ValueError(f"color sequence must have 3 or 4 components: {value!r}")
        for c in parts:
            if not 0 <= c <= 255:
                raise ValueError(f"color components must be in the range 0..255: {value!r}")
        return (parts[0], parts[1], parts[2], parts[3])
    raise ValueError(f"could not parse color: {value!r}")


def main(argv: Optional[List[str]] = None) -> int:
    """Script entry point: parse arguments and generate sample tiles.

    Args:
        argv: List of command-line arguments. Uses ``sys.argv[1:]`` if ``None``.

    Returns:
        Exit code. 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(
        prog="generate_sample_tiles.py",
        description="Generate sample tile PNGs for the tilepacker demo.",
    )
    parser.add_argument("--count", type=int, default=12, help="Number of tiles to generate (default 12).")
    parser.add_argument("--size", type=int, default=32, help="Pixel size of one tile side (default 32).")
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_tiles"),
        help="Output directory (default examples/sample_tiles).",
    )
    parser.add_argument(
        "--bg",
        default="#ff00ff",
        help="Background (= removal target) color. '#rrggbb'/'r,g,b'/'none', etc. (default #ff00ff).",
    )
    args = parser.parse_args(argv)

    try:
        bg = parse_bg(args.bg)
    except ValueError as exc:
        print(f"error: invalid --bg value: {exc}", file=sys.stderr)
        return 1

    try:
        saved = generate_tiles(args.count, args.size, args.out, bg)
    except (OSError, ValueError) as exc:
        print(f"error: failed to generate tiles: {exc}", file=sys.stderr)
        return 1

    bg_desc = "transparent" if bg is None else f"rgba{bg}"
    print(
        f"Generated {len(saved)} sample tiles in {os.path.abspath(args.out)} "
        f"({args.size}x{args.size}px, background {bg_desc})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
