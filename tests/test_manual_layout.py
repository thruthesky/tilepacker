"""Headless tests for the manual tileset layout feature.

When ``grid.rows`` is set (> 0) the preview shows a full rows x columns grid of
empty slots and the user places tiles at explicit positions: copy a cell on the
left, then click an empty slot in the preview. Empty interior slots become
transparent placeholder cells; trailing empties are dropped from the export.

These run under the ``offscreen`` Qt platform plugin. If PySide6 is not
installed, the whole module is skipped.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtCore, QtWidgets  # noqa: E402
from PIL import Image  # noqa: E402

from tilepacker.gui_app.main_window import MainWindow  # noqa: E402
from tilepacker.gui_app.model import GridSettings, ProjectModel, TileItem  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication instance for the whole test session."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _silence_modals(monkeypatch):
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(
            QtWidgets.QMessageBox, name, staticmethod(lambda *a, **k: None)
        )


def _sheet_png(tmp_path, size=(192, 192)):
    """Save an opaque sheet so cropped cells are non-empty."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = ((x * 7) % 256, (y * 5) % 256, 128, 255)
    p = tmp_path / "sheet.png"
    img.save(p, "PNG")
    return str(p)


# -- Model: placeholder + slot placement -------------------------------------
def test_placeholder_renders_transparent():
    grid = GridSettings(tile_width=64, tile_height=32)
    ph = TileItem.make_placeholder()
    assert ph.placeholder is True and ph.in_tileset is True
    cell = ph.render_cell(grid)
    assert cell.size == (64, 32)
    assert max(px[3] for px in cell.getdata()) == 0  # fully transparent


def test_place_in_tileset_slot_pads_placeholders():
    model = ProjectModel()
    real = TileItem("x", Image.new("RGBA", (64, 32), (0, 200, 0, 255)))
    model.tiles.append(real)  # a source-only tile (not in tileset)
    cell = TileItem("y", Image.new("RGBA", (64, 32), (200, 0, 0, 255)))
    # Place at slot 3: slots 0..2 become placeholders, 3 is the cell.
    model.place_in_tileset_slot(3, cell)
    ts = model.tileset_tiles()
    flags = [t.placeholder for t in ts]
    assert flags == [True, True, True, False]
    assert ts[3] is cell and cell.in_tileset is True


def test_place_fills_existing_placeholder_in_place():
    model = ProjectModel()
    cell_a = TileItem("a", Image.new("RGBA", (64, 32), (0, 200, 0, 255)))
    model.place_in_tileset_slot(2, cell_a)  # [ph, ph, A]
    cell_b = TileItem("b", Image.new("RGBA", (64, 32), (0, 0, 200, 255)))
    model.place_in_tileset_slot(0, cell_b)  # fill slot 0 -> [B, ph, A]
    ts = model.tileset_tiles()
    assert [t.placeholder for t in ts] == [False, True, False]
    assert ts[0] is cell_b and ts[2] is cell_a


def test_export_drops_trailing_placeholders_keeps_interior():
    model = ProjectModel()
    a = TileItem("a", Image.new("RGBA", (64, 32), (0, 200, 0, 255)))
    b = TileItem("b", Image.new("RGBA", (64, 32), (0, 0, 200, 255)))
    model.place_in_tileset_slot(1, a)  # [ph, A]
    model.place_in_tileset_slot(4, b)  # [ph, A, ph, ph, B]
    # Add two trailing placeholders that must be dropped on export.
    model.tiles.append(TileItem.make_placeholder())
    model.tiles.append(TileItem.make_placeholder())
    exported = model.export_tileset_tiles()
    assert [t.placeholder for t in exported] == [True, False, True, True, False]


def test_export_transparent_interior_cell(tmp_path):
    model = ProjectModel()
    model.grid = GridSettings(
        orientation="isometric", tile_width=64, tile_height=32,
        columns=8, fit_to_cell=True,
    )
    cell = TileItem("c", Image.new("RGBA", (64, 32), (0, 200, 0, 255)))
    model.place_in_tileset_slot(1, cell)  # slot 0 empty, slot 1 grass
    out = str(tmp_path / "ts.png")
    res = model.export(out, write_tsx=True)
    assert res.columns == 8 and res.tile_count == 2
    sheet = Image.open(out).convert("RGBA")
    slot0 = sheet.crop((0, 0, 64, 32))
    slot1 = sheet.crop((64, 0, 128, 32))
    assert max(px[3] for px in slot0.getdata()) == 0     # transparent gap
    assert max(px[3] for px in slot1.getdata()) == 255   # placed tile


def test_grid_settings_rows_roundtrip():
    g = GridSettings(rows=5)
    assert GridSettings.from_dict(g.to_dict()).rows == 5


def test_workspace_roundtrips_placeholders(tmp_path):
    model = ProjectModel()
    cell = TileItem("c", Image.new("RGBA", (64, 32), (0, 200, 0, 255)))
    # Save the source under a real path so it reloads.
    p = tmp_path / "c.png"
    cell.source.save(p, "PNG")
    cell.path = str(p)
    model.place_in_tileset_slot(2, cell)  # [ph, ph, C]
    ws = tmp_path / "ws.json"
    model.save_workspace(str(ws))
    loaded = ProjectModel()
    loaded.load_workspace(str(ws))
    ts = loaded.tileset_tiles()
    assert [t.placeholder for t in ts] == [True, True, False]


# -- Preview: empty-slot grid + click to place -------------------------------
def _iso_place_window(qapp, tmp_path, rows=3):
    win = MainWindow()
    win.import_images([_sheet_png(tmp_path)], notify=False)
    g = win.model.grid
    g.fit_to_cell = True
    g.orientation = "isometric"
    g.tile_width = 64
    g.tile_height = 32
    g.columns = 8
    g.rows = rows
    win.grid_panel.bind(g)
    return win


def test_rows_spinbox_syncs(qapp, tmp_path):
    win = _iso_place_window(qapp, tmp_path, rows=4)
    assert win.grid_panel.rows.value() == 4


def test_preview_shows_empty_grid_when_rows_set(qapp, tmp_path):
    win = _iso_place_window(qapp, tmp_path, rows=3)
    pc = win.preview_canvas
    pc.grab()  # force a paint so hit rects are built
    # 8 cols x 3 rows = 24 clickable slots, all currently empty.
    assert len(pc._hit_rects) == 24
    assert all(pc._slot_is_empty(i) for i, _ in enumerate(pc._hit_rects))


def test_place_at_slot_via_signal(qapp, tmp_path):
    win = _iso_place_window(qapp, tmp_path, rows=3)
    win._copied_tile = win.model.tiles[0].clone()  # pretend a cell was copied
    win.preview_canvas.set_paste_armed(True)
    win._on_preview_place_at(9)  # row 1, col 1
    ts = win.model.tileset_tiles()
    assert len(ts) == 10
    assert [t.placeholder for t in ts[:9]] == [True] * 9
    assert ts[9].placeholder is False


def test_cell_pick_copies_only_when_rows_set(qapp, tmp_path):
    win = _iso_place_window(qapp, tmp_path, rows=3)
    win.split_orient_combo.setCurrentIndex(1)  # isometric split
    win.split_w_spin.setValue(128)
    win.split_h_spin.setValue(64)
    win.split_toggle.setChecked(True)
    before = len(win.model.tileset_tiles())
    win._on_cell_picked((0, 0, 128, 64))
    # rows > 0: copied, not added.
    assert len(win.model.tileset_tiles()) == before
    assert win._copied_tile is not None


def test_cell_pick_appends_when_rows_zero(qapp, tmp_path):
    win = _iso_place_window(qapp, tmp_path, rows=0)
    win.split_orient_combo.setCurrentIndex(1)
    win.split_w_spin.setValue(128)
    win.split_h_spin.setValue(64)
    win.split_toggle.setChecked(True)
    before = len(win.model.tileset_tiles())
    win._on_cell_picked((0, 0, 128, 64))
    # rows == 0: appended immediately (original behavior).
    assert len(win.model.tileset_tiles()) == before + 1


def test_iso_hit_index_uses_diamond(qapp, tmp_path):
    """A click at a cell's diamond center hits that cell, not an overlapping box."""
    win = _iso_place_window(qapp, tmp_path, rows=3)
    pc = win.preview_canvas
    pc.grab()
    rect = next(r for r, i in pc._hit_rects if i == 5)
    assert pc._hit_index(rect.center()) == 5


# -- Rows > 0 implies uniform layout even with fit-to-cell unchecked ----------
def test_uniform_layout_when_rows_set_without_fit_to_cell():
    g = GridSettings(fit_to_cell=False, rows=4)
    assert g.uniform_layout() is True
    g2 = GridSettings(fit_to_cell=False, rows=0)
    assert g2.uniform_layout() is False


def test_rows_grid_shows_without_fit_to_cell(qapp, tmp_path):
    win = MainWindow()
    win.import_images([_sheet_png(tmp_path)], notify=False)
    g = win.model.grid
    g.fit_to_cell = False  # user did NOT check "Fit each tile to one cell"
    g.orientation = "isometric"
    g.tile_width = 64
    g.tile_height = 32
    g.columns = 8
    g.rows = 4
    win.grid_panel.bind(g)
    pc = win.preview_canvas
    pc.grab()  # force a paint so hit rects are built
    # 8 cols x 4 rows empty-slot grid is shown despite fit_to_cell being off.
    assert len(pc._hit_rects) == 32
    assert all(pc._slot_is_empty(i) for i, _ in enumerate(pc._hit_rects))


def test_export_uniform_when_rows_set_without_fit(tmp_path):
    model = ProjectModel()
    model.grid = GridSettings(
        orientation="isometric", tile_width=64, tile_height=32,
        columns=8, rows=4, fit_to_cell=False,
    )
    cell = TileItem("c", Image.new("RGBA", (64, 32), (0, 200, 0, 255)))
    model.place_in_tileset_slot(1, cell)  # slot 0 empty, slot 1 grass
    out = str(tmp_path / "ts.png")
    res = model.export(out, write_tsx=True)
    # Uniform export (one cell per tile), not the size-preserving shelf layout.
    assert res.columns == 8 and res.tile_count == 2
