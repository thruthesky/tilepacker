"""Shared pytest fixtures.

Provides a helper for creating solid-color tile images and fixtures that build
lists of tiles with distinct colors. All images are created in Pillow's RGBA
mode.
"""

from __future__ import annotations

from typing import List, Tuple

import pytest
from PIL import Image

from tilepacker.core.config import RGBA


def make_tile(color, size: Tuple[int, int] = (32, 32)) -> Image.Image:
    """Create a solid-color RGBA tile image of the given color and size.

    Args:
        color: Fill color. An ``(r, g, b)`` or ``(r, g, b, a)`` tuple.
        size: ``(width, height)`` size in pixels. Defaults to 32x32.

    Returns:
        A new RGBA image filled with the given color.
    """
    col = tuple(color)
    if len(col) == 3:
        col = (col[0], col[1], col[2], 255)
    return Image.new("RGBA", (int(size[0]), int(size[1])), col)


@pytest.fixture
def make_tile_fn():
    """Factory fixture that returns :func:`make_tile` itself."""
    return make_tile


# A palette of sufficiently distinct colors. Each color is in (r, g, b, a) form.
_PALETTE: List[RGBA] = [
    (255, 0, 0, 255),
    (0, 255, 0, 255),
    (0, 0, 255, 255),
    (255, 255, 0, 255),
    (255, 0, 255, 255),
    (0, 255, 255, 255),
]


@pytest.fixture
def color_palette() -> List[RGBA]:
    """A palette of 6 distinct opaque colors (list of RGBA tuples)."""
    return list(_PALETTE)


@pytest.fixture
def color_tiles() -> List[Image.Image]:
    """A list of 6 distinctly colored 32x32 tiles (all unique pixels)."""
    return [make_tile(c, (32, 32)) for c in _PALETTE]


@pytest.fixture
def saved_tile_paths(tmp_path) -> List[str]:
    """Save the 6 palette-colored tiles as PNGs and return their paths."""
    paths: List[str] = []
    for i, c in enumerate(_PALETTE):
        p = tmp_path / f"tile_{i:02d}.png"
        make_tile(c, (32, 32)).save(p, "PNG")
        paths.append(str(p))
    return paths
