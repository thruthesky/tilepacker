"""Unit tests for the GUI's non-Qt core: image editing, the project model,
and the isometric grid metadata in the Tiled definition files.

These tests import only Pillow and the pure helpers (no PySide6), so they run
in the standard headless test suite.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET

from PIL import Image

from tilepacker.gui_app import imageedit
from tilepacker.gui_app.model import TileEdit, GridSettings, TileItem, ProjectModel
from tilepacker.core import tiled


def _solid(color, size=(64, 32)):
    return Image.new("RGBA", size, color)


# --------------------------------------------------------------------------
# imageedit
# --------------------------------------------------------------------------
def test_rotate_zero_is_copy_not_same_object():
    src = _solid((10, 20, 30, 255))
    out = imageedit.rotate_image(src, 0)
    assert out is not src
    assert out.size == src.size


def test_rotate_expands_canvas():
    src = _solid((10, 20, 30, 255), (40, 20))
    out = imageedit.rotate_image(src, 45, expand=True)
    assert out.width > 40 and out.height > 20


def test_flip_horizontal_and_vertical():
    src = Image.new("RGBA", (2, 1))
    src.putpixel((0, 0), (255, 0, 0, 255))
    src.putpixel((1, 0), (0, 0, 255, 255))
    out = imageedit.flip_image(src, horizontal=True)
    assert out.getpixel((0, 0)) == (0, 0, 255, 255)
    assert out.getpixel((1, 0)) == (255, 0, 0, 255)


def test_crop_clamps_to_bounds():
    src = _solid((1, 2, 3, 255), (32, 32))
    out = imageedit.crop_image(src, (10, 10, 999, 999))
    assert out.size == (22, 22)


def test_crop_degenerate_returns_copy():
    src = _solid((1, 2, 3, 255), (16, 16))
    out = imageedit.crop_image(src, (5, 5, 5, 5))
    assert out.size == (16, 16)


def test_grayscale_preserves_alpha_and_desaturates():
    src = _solid((200, 50, 25, 128))
    out = imageedit.to_grayscale(src)
    r, g, b, a = out.getpixel((0, 0))
    assert r == g == b
    assert a == 128


def test_hue_shift_changes_rgb_keeps_alpha():
    src = _solid((200, 50, 25, 200))
    out = imageedit.adjust_hue(src, 120)
    assert out.getpixel((0, 0))[:3] != (200, 50, 25)
    assert out.getpixel((0, 0))[3] == 200


def test_saturation_zero_is_grayscale():
    src = _solid((200, 50, 25, 255))
    out = imageedit.adjust_saturation(src, 0.0)
    r, g, b, _ = out.getpixel((0, 0))
    assert abs(r - g) <= 1 and abs(g - b) <= 1


def test_brightness_and_contrast_keep_alpha():
    src = _solid((120, 120, 120, 77))
    assert imageedit.adjust_brightness(src, 0.5).getpixel((0, 0))[3] == 77
    assert imageedit.adjust_contrast(src, 1.5).getpixel((0, 0))[3] == 77


def test_edit_does_not_mutate_source():
    src = _solid((200, 100, 50, 255))
    imageedit.adjust_hue(src, 90)
    imageedit.to_grayscale(src)
    imageedit.rotate_image(src, 30)
    assert src.getpixel((0, 0)) == (200, 100, 50, 255)


# --------------------------------------------------------------------------
# model: TileItem / ProjectModel
# --------------------------------------------------------------------------
def test_tileitem_identity_render_is_copy():
    item = TileItem("x.png", _solid((9, 8, 7, 255)))
    out = item.render()
    assert out is not item.source
    assert out.getpixel((0, 0)) == (9, 8, 7, 255)


def test_tileitem_render_cell_matches_grid_size():
    item = TileItem("x.png", _solid((1, 2, 3, 255), (100, 100)))
    grid = GridSettings()  # isometric, 64x32 by default
    cell = item.render_cell(grid)
    assert cell.size == (64, 32)


def test_tileedit_reset():
    e = TileEdit(rotation=45, hue=90, grayscale=True, bg_remove=True)
    e.reset()
    assert e.rotation == 0 and e.hue == 0 and e.grayscale is False and e.bg_remove is False


def test_projectmodel_add_remove_move_clear(tmp_path):
    paths = []
    for i, c in enumerate([(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)]):
        p = tmp_path / f"t{i}.png"
        _solid(c, (50, 50)).save(p)
        paths.append(str(p))
    m = ProjectModel()
    added, failed = m.add_paths(paths)
    assert added == 3 and failed == []
    # move first to last
    new_index = m.move(0, 2)
    assert new_index == 2
    m.remove(0)
    assert len(m.tiles) == 2
    m.clear()
    assert m.tiles == []


def test_projectmodel_add_paths_reports_failures(tmp_path):
    good = tmp_path / "g.png"
    _solid((1, 1, 1, 255)).save(good)
    m = ProjectModel()
    added, failed = m.add_paths([str(good), str(tmp_path / "missing.png")])
    assert added == 1
    assert len(failed) == 1


def test_projectmodel_default_grid_is_isometric_64x32():
    m = ProjectModel()
    assert m.grid.orientation == "isometric"
    assert (m.grid.tile_width, m.grid.tile_height) == (64, 32)


# --------------------------------------------------------------------------
# export: orthogonal vs isometric grid metadata
# --------------------------------------------------------------------------
def test_export_orthogonal_has_no_grid_element(tmp_path):
    m = ProjectModel()
    m.grid.orientation = "orthogonal"
    for c in [(255, 0, 0, 255), (0, 255, 0, 255)]:
        p = tmp_path / f"{c[0]}.png"
        _solid(c).save(p)
        m.add_paths([str(p)])
    for t in m.tiles:
        t.in_tileset = True
    result = m.export(str(tmp_path / "ortho.png"), write_tsx=True)
    root = ET.parse(result.tsx_path).getroot()
    assert root.find("grid") is None


def test_export_isometric_writes_grid_element(tmp_path):
    m = ProjectModel()  # isometric by default
    for c in [(255, 0, 0, 255), (0, 255, 0, 255)]:
        p = tmp_path / f"{c[0]}.png"
        _solid(c).save(p)
        m.add_paths([str(p)])
    for t in m.tiles:
        t.in_tileset = True
    result = m.export(str(tmp_path / "iso.png"), write_tsx=True, write_tsj=True)
    root = ET.parse(result.tsx_path).getroot()
    grid = root.find("grid")
    assert grid is not None
    assert grid.get("orientation") == "isometric"
    assert grid.get("width") == "64"
    assert grid.get("height") == "32"
    data = json.loads(open(result.tsj_path, encoding="utf-8").read())
    assert data["grid"] == {"orientation": "isometric", "width": 64, "height": 32}


# --------------------------------------------------------------------------
# tiled: build_tsx/build_tsj grid argument directly
# --------------------------------------------------------------------------
def test_build_tsx_grid_optional():
    base = dict(
        name="t", image_source="t.png", image_width=10, image_height=10,
        tile_width=5, tile_height=5, tile_count=4, columns=2,
    )
    assert "<grid" not in tiled.build_tsx(**base)
    with_grid = tiled.build_tsx(**base, grid_orientation="isometric", grid_width=128, grid_height=64)
    assert '<grid orientation="isometric" width="128" height="64"/>' in with_grid


def test_build_tsj_grid_optional():
    base = dict(
        name="t", image_source="t.png", image_width=10, image_height=10,
        tile_width=5, tile_height=5, tile_count=4, columns=2,
    )
    assert "grid" not in json.loads(tiled.build_tsj(**base))
    data = json.loads(tiled.build_tsj(**base, grid_orientation="isometric", grid_width=128, grid_height=64))
    assert data["grid"]["orientation"] == "isometric"


# --------------------------------------------------------------------------
# imageedit: diamond mask
# --------------------------------------------------------------------------
def test_diamond_mask_clears_corners_keeps_center():
    src = _solid((255, 0, 0, 255), (64, 64))
    out = imageedit.diamond_mask(src, 64, 32)
    assert out.size == (64, 64)
    assert out.getpixel((0, 0))[3] == 0       # corner outside the diamond
    assert out.getpixel((32, 32))[3] == 255   # center inside the diamond


def test_diamond_in_render_pipeline_uses_grid_ratio():
    item = TileItem("x.png", _solid((0, 200, 0, 255), (64, 64)))
    item.edit.diamond = True
    out = item.render(GridSettings(tile_width=64, tile_height=32))
    assert out.getpixel((0, 0))[3] == 0
    assert out.getpixel((32, 32))[3] == 255


# --------------------------------------------------------------------------
# model: serialization round-trips
# --------------------------------------------------------------------------
def test_tileedit_dict_roundtrip():
    e = TileEdit(rotation=90, hue=45, crop=(1, 2, 30, 40), bg_remove=True,
                 bg_color=(255, 0, 255, 255), diamond=True, scale=2.0)
    e2 = TileEdit.from_dict(e.to_dict())
    assert e2.rotation == 90 and e2.hue == 45
    assert e2.crop == (1, 2, 30, 40)
    assert e2.bg_color == (255, 0, 255, 255)
    assert e2.diamond is True and e2.scale == 2.0


def test_gridsettings_dict_roundtrip():
    g = GridSettings(orientation="orthogonal", tile_width=128, tile_height=64,
                     columns=4, background=(10, 20, 30, 255), fit_to_cell=True)
    g2 = GridSettings.from_dict(g.to_dict())
    assert g2.orientation == "orthogonal"
    assert (g2.tile_width, g2.tile_height) == (128, 64)
    assert g2.columns == 4
    assert g2.background == (10, 20, 30, 255)
    assert g2.fit_to_cell is True


# --------------------------------------------------------------------------
# model: workspace save / load
# --------------------------------------------------------------------------
def test_workspace_save_and_load_roundtrip(tmp_path):
    paths = []
    for i, c in enumerate([(255, 0, 0, 255), (0, 255, 0, 255)]):
        p = tmp_path / f"w{i}.png"
        _solid(c, (40, 40)).save(p)
        paths.append(str(p))
    m = ProjectModel()
    m.add_paths(paths)
    m.grid.tile_width = 128
    m.tiles[0].edit.diamond = True
    m.tiles[1].edit.rotation = 90
    saved = m.save_workspace(str(tmp_path / "proj"))   # extension auto-added
    assert saved.endswith(".json")

    m2 = ProjectModel()
    loaded, failed = m2.load_workspace(saved)
    assert loaded == 2 and failed == []
    assert m2.grid.tile_width == 128
    assert m2.tiles[0].edit.diamond is True
    assert m2.tiles[1].edit.rotation == 90


def test_workspace_load_reports_missing_tiles(tmp_path):
    good = tmp_path / "ok.png"
    _solid((1, 2, 3, 255)).save(good)
    m = ProjectModel()
    m.add_paths([str(good)])
    saved = m.save_workspace(str(tmp_path / "proj.json"))
    os.remove(good)   # make the recorded source unloadable
    m2 = ProjectModel()
    loaded, failed = m2.load_workspace(saved)
    assert loaded == 0
    assert len(failed) == 1


# --------------------------------------------------------------------------
# model: undo / redo history
# --------------------------------------------------------------------------
def test_undo_redo_add_and_edit(tmp_path):
    p = tmp_path / "u.png"
    _solid((9, 9, 9, 255), (30, 30)).save(p)
    m = ProjectModel()
    m.add_paths([str(p)])
    m.commit()
    m.tiles[0].edit.rotation = 45
    m.commit()

    assert m.undo() is True
    assert m.tiles[0].edit.rotation == 0
    assert m.redo() is True
    assert m.tiles[0].edit.rotation == 45

    assert m.undo() is True   # undo edit
    assert m.undo() is True   # undo add
    assert len(m.tiles) == 0
    assert m.undo() is False  # nothing left


def test_commit_coalesce_collapses_consecutive_edits(tmp_path):
    p = tmp_path / "c.png"
    _solid((9, 9, 9, 255), (30, 30)).save(p)
    m = ProjectModel()
    m.add_paths([str(p)])
    m.commit()
    for r in (10, 20, 30):
        m.tiles[0].edit.rotation = r
        m.commit(coalesce="edit")
    # A single undo reverts the whole coalesced gesture back to before it.
    assert m.undo() is True
    assert m.tiles[0].edit.rotation == 0
