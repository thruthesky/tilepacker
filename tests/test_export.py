"""Tests for tilepacker.core.export."""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET

from PIL import Image

from tilepacker.core import export
from tilepacker.core.config import PackConfig

from .conftest import make_tile


# --- natural_sort_key ------------------------------------------------------
def test_natural_sort_key_orders_numbers():
    names = ["tile10", "tile2", "tile1"]
    ordered = sorted(names, key=export.natural_sort_key)
    assert ordered == ["tile1", "tile2", "tile10"]


# --- preprocess_tiles / finalize_tiles -------------------------------------
def test_preprocess_tiles_bg_remove():
    img = make_tile((255, 0, 0, 255), (8, 8))
    cfg = PackConfig(bg_remove=True, bg_color=(255, 0, 0, 255))
    out = export.preprocess_tiles([img], cfg)
    assert len(out) == 1
    assert out[0].getpixel((0, 0))[3] == 0  # Red background made transparent.
    # The original is not modified.
    assert img.getpixel((0, 0)) == (255, 0, 0, 255)


def test_finalize_tiles_dedup_and_drop_empty():
    red = make_tile((255, 0, 0, 255), (8, 8))
    red2 = make_tile((255, 0, 0, 255), (8, 8))
    empty = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    cfg = PackConfig(deduplicate=True, drop_empty=True)
    out = export.finalize_tiles([red, empty, red2], cfg)
    # Drop empty tiles, then deduplicate -> a single red tile.
    assert len(out) == 1


# --- export_tileset --------------------------------------------------------
def test_export_tileset_creates_png_tsx_tsj(tmp_path):
    tiles = [make_tile((i * 30, 0, 0, 255), (16, 16)) for i in range(4)]
    cfg = PackConfig(tile_width=16, tile_height=16, columns=2, name="set")
    out_png = tmp_path / "out.png"
    result = export.export_tileset(
        tiles, cfg, str(out_png), write_tsx=True, write_tsj=True
    )
    assert os.path.exists(result.image_path)
    assert result.tsx_path is not None and os.path.exists(result.tsx_path)
    assert result.tsj_path is not None and os.path.exists(result.tsj_path)
    assert result.tile_count == 4
    assert result.columns == 2 and result.rows == 2
    assert result.width == 32 and result.height == 32

    # The image source in the .tsx is the PNG basename.
    root = ET.fromstring(open(result.tsx_path, encoding="utf-8").read())
    assert root.find("image").attrib["source"] == "out.png"
    # The type in the .tsj is tileset.
    data = json.loads(open(result.tsj_path, encoding="utf-8").read())
    assert data["type"] == "tileset"
    # Check the size of the saved PNG.
    with Image.open(result.image_path) as im:
        assert im.size == (32, 32)


def test_export_tileset_tsx_only(tmp_path):
    tiles = [make_tile((0, 255, 0, 255), (16, 16))]
    cfg = PackConfig(tile_width=16, tile_height=16)
    out_png = tmp_path / "a.png"
    result = export.export_tileset(tiles, cfg, str(out_png))
    assert result.tsx_path is not None
    assert result.tsj_path is None


# --- pack_from_files -------------------------------------------------------
def test_pack_from_files_roundtrip(tmp_path, saved_tile_paths):
    cfg = PackConfig(tile_width=32, tile_height=32, columns=3, sort="natural")
    out_png = tmp_path / "packed.png"
    result = export.pack_from_files(
        saved_tile_paths, cfg, str(out_png), write_tsj=True
    )
    assert result.tile_count == 6
    assert result.columns == 3 and result.rows == 2
    assert os.path.exists(result.image_path)
    with Image.open(result.image_path) as im:
        assert im.size == (96, 64)


def test_pack_from_files_dedup(tmp_path):
    # Save 3 same-color tiles -> 1 after dedup.
    paths = []
    for i in range(3):
        p = tmp_path / f"same_{i}.png"
        make_tile((255, 0, 0, 255), (16, 16)).save(p, "PNG")
        paths.append(str(p))
    cfg = PackConfig(tile_width=16, tile_height=16, deduplicate=True)
    out_png = tmp_path / "dd.png"
    result = export.pack_from_files(paths, cfg, str(out_png))
    assert result.tile_count == 1


# --- pack_from_spritesheet (slice the sheet, then repack round-trip) -------
def test_pack_from_spritesheet_roundtrip(tmp_path):
    # Build a 4x1 spritesheet (each cell 16x16, distinct colors).
    sheet = Image.new("RGBA", (64, 16), (0, 0, 0, 0))
    px = sheet.load()
    colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)]
    for c_idx, col in enumerate(colors):
        for y in range(16):
            for x in range(16):
                px[c_idx * 16 + x, y] = col
    sheet_path = tmp_path / "sheet.png"
    sheet.save(sheet_path, "PNG")

    cfg = PackConfig(tile_width=16, tile_height=16, columns=2)
    out_png = tmp_path / "repacked.png"
    result = export.pack_from_spritesheet(
        str(sheet_path), cfg, str(out_png), write_tsj=True
    )
    # Rearrange 4 tiles into a 2x2 layout.
    assert result.tile_count == 4
    assert result.columns == 2 and result.rows == 2
    assert os.path.exists(result.image_path)
    with Image.open(result.image_path) as im:
        assert im.size == (32, 32)
