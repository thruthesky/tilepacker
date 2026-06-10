"""Duplicate tile removal and empty (transparent) tile removal.

This module is used in the post-processing stage of the packing pipeline. It
merges pixel-identical tiles into one (:func:`deduplicate`) and filters out
fully transparent tiles (:func:`drop_empty_tiles`).

Implementation policy:
  * All images are handled in Pillow RGBA mode.
  * numpy is an optional accelerator; without it, pure Pillow produces the
    same result.
  * Source images are never mutated.

Dependencies: Pillow required, numpy optional.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Tuple

from PIL import Image

try:  # numpy is an optional accelerator.
    import numpy as np

    _HAS_NUMPY = True
except Exception:  # pragma: no cover - guard for environments without numpy
    _HAS_NUMPY = False

__all__ = [
    "image_signature",
    "deduplicate",
    "drop_empty_tiles",
]


def _as_rgba(img: Image.Image) -> Image.Image:
    """Return a copy converted to RGBA mode, or the original.

    If the image is already in RGBA mode, it is returned as is with no
    conversion cost; otherwise a converted new image is returned. In either
    case the original is never mutated.
    """
    if img.mode == "RGBA":
        return img
    return img.convert("RGBA")


def image_signature(img: Image.Image) -> bytes:
    """Compute the pixel signature of a tile image.

    Images with the same size and same pixels (RGBA) always return the same
    signature, and a different size or pixels returns a (practically) different
    signature.

    Implementation: convert to RGBA, then concatenate (width, height) with the
    raw pixel bytes to build a SHA-1 digest. Since the size is included in the
    signature, two images with coincidentally identical pixel bytes still get
    different signatures when their sizes differ.

    Args:
        img: The Pillow image whose signature is computed.

    Returns:
        A 20-byte SHA-1 digest.
    """
    rgba = _as_rgba(img)
    width, height = rgba.size
    hasher = hashlib.sha1()
    # Serialize the size as fixed-width 8 bytes to keep a clear boundary with the pixel bytes.
    hasher.update(width.to_bytes(4, "little"))
    hasher.update(height.to_bytes(4, "little"))
    hasher.update(rgba.tobytes())
    return hasher.digest()


def deduplicate(
    tiles: List[Image.Image],
) -> Tuple[List[Image.Image], List[int]]:
    """Merge pixel-identical duplicate tiles into one.

    Preserving first-appearance order, tiles with identical pixels are mapped
    to the single tile that appeared first.

    Args:
        tiles: The source list of tile images. Neither the source list nor the
            images within it are mutated.

    Returns:
        An ``(unique_tiles, index_map)`` tuple.
          * ``unique_tiles``: the deduplicated list of unique tiles (in
            first-appearance order).
          * ``index_map``: a list of the same length as the source, where
            ``index_map[i]`` is the index into ``unique_tiles`` to which the
            ``i``-th source tile maps.
    """
    unique_tiles: List[Image.Image] = []
    index_map: List[int] = []
    seen: Dict[bytes, int] = {}

    for tile in tiles:
        sig = image_signature(tile)
        idx = seen.get(sig)
        if idx is None:
            idx = len(unique_tiles)
            seen[sig] = idx
            unique_tiles.append(tile)
        index_map.append(idx)

    return unique_tiles, index_map


def _is_empty(img: Image.Image, alpha_threshold: int) -> bool:
    """Check whether every pixel's alpha is at or below ``alpha_threshold``.

    With numpy available, this uses a vectorized operation; without it, it
    extracts only the alpha channel and checks the maximum alpha via
    ``getextrema()``. Both paths produce the same result.
    """
    rgba = _as_rgba(img)
    alpha = rgba.getchannel("A")

    if _HAS_NUMPY:
        arr = np.asarray(alpha)
        if arr.size == 0:
            return True
        return bool(arr.max() <= alpha_threshold)

    # Pure Pillow path: get the maximum value of the alpha channel.
    extrema = alpha.getextrema()  # (min, max)
    if extrema is None:
        return True
    return extrema[1] <= alpha_threshold


def drop_empty_tiles(
    tiles: List[Image.Image],
    *,
    alpha_threshold: int = 0,
) -> Tuple[List[Image.Image], List[int]]:
    """Remove fully transparent tiles.

    A tile whose every pixel has an alpha value at or below ``alpha_threshold``
    is treated as empty and excluded from the result.

    Args:
        tiles: The source list of tile images. The source is never mutated.
        alpha_threshold: A tile with only alpha values at or below this is
            considered empty. The default of 0 means "every pixel is fully
            transparent".

    Returns:
        A ``(kept_tiles, kept_original_indices)`` tuple.
          * ``kept_tiles``: the remaining tiles after excluding empty ones
            (order preserved).
          * ``kept_original_indices``: the list of original indices of each
            remaining tile.
    """
    kept_tiles: List[Image.Image] = []
    kept_original_indices: List[int] = []

    for i, tile in enumerate(tiles):
        if not _is_empty(tile, alpha_threshold):
            kept_tiles.append(tile)
            kept_original_indices.append(i)

    return kept_tiles, kept_original_indices
