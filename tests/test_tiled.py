"""Tests for tilepacker.core.tiled."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from tilepacker.core import tiled


_META = dict(
    name="myset",
    image_source="myset.png",
    image_width=128,
    image_height=64,
    tile_width=32,
    tile_height=32,
    tile_count=8,
    columns=4,
)


# --- build_tsx -------------------------------------------------------------
def test_build_tsx_parses_as_xml():
    text = tiled.build_tsx(**_META)
    root = ET.fromstring(text)
    assert root.tag == "tileset"
    assert root.attrib["name"] == "myset"
    assert root.attrib["tilewidth"] == "32"
    assert root.attrib["tileheight"] == "32"
    assert root.attrib["tilecount"] == "8"
    assert root.attrib["columns"] == "4"
    img = root.find("image")
    assert img is not None
    assert img.attrib["source"] == "myset.png"
    assert img.attrib["width"] == "128"
    assert img.attrib["height"] == "64"


def test_build_tsx_omits_zero_margin_spacing():
    text = tiled.build_tsx(**_META, margin=0, spacing=0)
    root = ET.fromstring(text)
    assert "margin" not in root.attrib
    assert "spacing" not in root.attrib


def test_build_tsx_includes_positive_margin_spacing():
    text = tiled.build_tsx(**_META, margin=2, spacing=3)
    root = ET.fromstring(text)
    assert root.attrib["margin"] == "2"
    assert root.attrib["spacing"] == "3"


def test_build_tsx_declares_xml_header():
    text = tiled.build_tsx(**_META)
    assert text.startswith("<?xml")


# --- build_tsj -------------------------------------------------------------
def test_build_tsj_parses_as_json_and_type():
    text = tiled.build_tsj(**_META)
    data = json.loads(text)
    assert data["type"] == "tileset"
    assert data["name"] == "myset"
    assert data["image"] == "myset.png"
    assert data["imagewidth"] == 128
    assert data["imageheight"] == 64
    assert data["tilewidth"] == 32
    assert data["tileheight"] == 32
    assert data["tilecount"] == 8
    assert data["columns"] == 4


def test_build_tsj_includes_margin_spacing():
    data = json.loads(tiled.build_tsj(**_META, margin=5, spacing=7))
    assert data["margin"] == 5
    assert data["spacing"] == 7


# --- write_tsx / write_tsj -------------------------------------------------
def test_write_tsx_writes_file(tmp_path):
    path = tmp_path / "out.tsx"
    returned = tiled.write_tsx(str(path), **_META)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert content == returned
    ET.fromstring(content)  # Must be parseable.


def test_write_tsj_writes_file(tmp_path):
    path = tmp_path / "out.tsj"
    returned = tiled.write_tsj(str(path), **_META)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["type"] == "tileset"
    assert returned == path.read_text(encoding="utf-8")
