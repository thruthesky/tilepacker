"""Regression tests for bugs found and fixed during adversarial review.

Each test guarantees that a defect reproduced by the review does not occur
again. Related issues:
  * With extrude>0, the margin/spacing in the .tsx/.tsj is misaligned with the
    actual PNG content coordinates (CRITICAL).
  * imageops.is_empty crashes on a 0x0 image in the pure-Pillow path (MEDIUM).
  * resize/rmbg silently overwrites inputs that share the same basename
    (MEDIUM).
  * _sample_corner_bg picks the wrong RGB-mode background when alpha differs
    (LOW).
  * An -o output without an extension does not get .png appended automatically
    (LOW).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from PIL import Image

from tilepacker import cli
from tilepacker.core import export, imageops, slicer
from tilepacker.core.config import PackConfig


def _solid(color, size=16):
    """Build a solid-color RGBA tile."""
    return Image.new("RGBA", (size, size), color)


# ---------------------------------------------------------------------------
# CRITICAL: extrude <-> .tsx margin/spacing coordinate alignment (round-trip)
# ---------------------------------------------------------------------------
def _read_tsx_grid(tsx_path):
    """Read (margin, spacing, tilewidth, tileheight, columns) from the generated .tsx."""
    root = ET.parse(tsx_path).getroot()
    margin = int(root.get("margin", "0"))
    spacing = int(root.get("spacing", "0"))
    tw = int(root.get("tilewidth"))
    th = int(root.get("tileheight"))
    columns = int(root.get("columns"))
    return margin, spacing, tw, th, columns


def _assert_roundtrip(tmp_path, extrude, margin, spacing):
    """Verify that re-slicing the packed PNG with the .tsx margin/spacing restores the input tiles."""
    colors = [
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
        (255, 255, 0, 255),
        (255, 0, 255, 255),
    ]
    tiles = [_solid(c) for c in colors]
    cfg = PackConfig(
        tile_width=16,
        tile_height=16,
        columns=3,
        margin=margin,
        spacing=spacing,
        extrude=extrude,
        resize_mode="none",
    )
    out = tmp_path / f"ts_e{extrude}.png"
    result = export.export_tileset(tiles, cfg, str(out), write_tsx=True)

    tsx_margin, tsx_spacing, tw, th, columns = _read_tsx_grid(result.tsx_path)
    # The Tiled definition file must record the extrude-corrected values.
    assert tsx_margin == margin + extrude
    assert tsx_spacing == spacing + 2 * extrude

    # Slicing with the .tsx margin/spacing restores the original content exactly.
    packed = Image.open(result.image_path).convert("RGBA")
    sliced = slicer.slice_image(
        packed, tw, th, margin=tsx_margin, spacing=tsx_spacing
    )
    # The first 5 cells must match the original colors (checked via the center pixel).
    for original_color, cell in zip(colors, sliced[: len(colors)]):
        center = cell.getpixel((tw // 2, th // 2))
        assert center == original_color


def test_extrude_tsx_roundtrip_no_extrude(tmp_path):
    _assert_roundtrip(tmp_path, extrude=0, margin=0, spacing=0)


def test_extrude_tsx_roundtrip_basic(tmp_path):
    _assert_roundtrip(tmp_path, extrude=2, margin=0, spacing=0)


def test_extrude_tsx_roundtrip_with_margin_spacing(tmp_path):
    _assert_roundtrip(tmp_path, extrude=2, margin=4, spacing=1)


def test_tsj_shares_effective_margin_spacing(tmp_path):
    """The .tsj also carries the extrude-corrected margin/spacing."""
    import json

    tiles = [_solid((255, 0, 0, 255)), _solid((0, 255, 0, 255))]
    cfg = PackConfig(tile_width=16, tile_height=16, columns=2, extrude=3, spacing=1, margin=2)
    out = tmp_path / "ts.png"
    result = export.export_tileset(tiles, cfg, str(out), write_tsx=False, write_tsj=True)
    data = json.loads(open(result.tsj_path, encoding="utf-8").read())
    assert data["margin"] == 2 + 3
    assert data["spacing"] == 1 + 2 * 3


# ---------------------------------------------------------------------------
# MEDIUM: is_empty on a 0x0 image (same result for numpy/Pillow paths)
# ---------------------------------------------------------------------------
def test_is_empty_zero_size_both_paths():
    img = Image.new("RGBA", (0, 0))
    saved = imageops._HAS_NUMPY
    try:
        imageops._HAS_NUMPY = True
        assert imageops.is_empty(img) is True
        imageops._HAS_NUMPY = False
        assert imageops.is_empty(img) is True  # Same result, no crash
    finally:
        imageops._HAS_NUMPY = saved


# ---------------------------------------------------------------------------
# LOW: _sample_corner_bg must pick the mode based on RGB only
# ---------------------------------------------------------------------------
def test_sample_corner_bg_uses_rgb_only():
    img = Image.new("RGBA", (2, 2))
    px = img.load()
    px[0, 0] = (255, 255, 255, 0)    # White, transparent
    px[1, 0] = (255, 255, 255, 255)  # White, opaque
    px[0, 1] = (200, 200, 200, 255)  # Gray
    px[1, 1] = (200, 200, 200, 255)  # Gray
    bg = imageops._sample_corner_bg(img)
    # By RGB, white 2 vs gray 2 is a tie -> white must win by insertion order.
    assert bg[:3] == (255, 255, 255)


# ---------------------------------------------------------------------------
# MEDIUM: resize/rmbg must not overwrite on a basename collision
# ---------------------------------------------------------------------------
def test_resize_basename_collision_preserves_all(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _solid((255, 0, 0, 255), 16).save(tmp_path / "a" / "tile.png")
    _solid((0, 0, 255, 255), 16).save(tmp_path / "b" / "tile.png")
    out_dir = tmp_path / "out"
    rc = cli.main([
        "resize",
        str(tmp_path / "a" / "tile.png"),
        str(tmp_path / "b" / "tile.png"),
        "-o", str(out_dir), "-tw", "8", "-th", "8", "--resize-mode", "none",
    ])
    assert rc == 0
    produced = sorted(p.name for p in out_dir.iterdir())
    # Both inputs must survive (no overwriting).
    assert len(produced) == 2
    assert "tile.png" in produced


def test_rmbg_basename_collision_preserves_all(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _solid((255, 0, 255, 255), 16).save(tmp_path / "a" / "tile.png")
    _solid((0, 255, 0, 255), 16).save(tmp_path / "b" / "tile.png")
    out_dir = tmp_path / "out"
    rc = cli.main([
        "rmbg",
        str(tmp_path / "a" / "tile.png"),
        str(tmp_path / "b" / "tile.png"),
        "-o", str(out_dir),
    ])
    assert rc == 0
    assert len(list(out_dir.iterdir())) == 2


# ---------------------------------------------------------------------------
# LOW: an -o without an extension gets .png appended automatically
# ---------------------------------------------------------------------------
def test_output_without_extension_gets_png(tmp_path):
    tiles = [_solid((255, 0, 0, 255))]
    cfg = PackConfig(tile_width=16, tile_height=16)
    out = tmp_path / "noext"
    result = export.export_tileset(tiles, cfg, str(out), write_tsx=True)
    assert result.image_path.endswith(".png")
    assert (tmp_path / "noext.png").exists()
    # The image source in the .tsx also carries the .png extension.
    root = ET.parse(result.tsx_path).getroot()
    assert root.find("image").get("source").endswith(".png")
