"""Headless tests for the Grid Split feature (split a source into cells, copy
one cell out, and paste it into the tileset).

These run under the ``offscreen`` Qt platform plugin. If PySide6 is not
installed, the whole module is skipped.
"""

from __future__ import annotations

import os

# Must be set before any QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtWidgets  # noqa: E402
from PIL import Image  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication instance for the whole test session."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _silence_modals(monkeypatch):
    """Prevent modal dialogs from blocking the headless run."""
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(
            QtWidgets.QMessageBox, name, staticmethod(lambda *a, **k: None)
        )


def _sheet_png(tmp_path, size=(192, 192)):
    """Save a sheet whose pixels vary by position (so cell crops differ)."""
    img = Image.new("RGBA", size, (0, 0, 0, 255))
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = (x % 256, y % 256, 128, 255)
    p = tmp_path / "sheet.png"
    img.save(p, "PNG")
    return str(p)


# --------------------------------------------------------------------------
# EditorCanvas split geometry
# --------------------------------------------------------------------------
def test_editor_split_grid_dims_and_cell_box(qapp):
    from tilepacker.gui_app.editor_canvas import EditorCanvas

    ec = EditorCanvas()
    ec.resize(400, 400)
    ec.set_image(Image.new("RGBA", (192, 192), (1, 2, 3, 255)))
    ec.set_split_mode(True, 64, 32)

    assert ec._split_mode is True
    assert ec._split_grid_dims() == (192, 192, 64, 32)
    # 192/64 = 3 columns, 192/32 = 6 rows.
    assert ec._cell_box(0, 0) == (0, 0, 64, 32)
    assert ec._cell_box(1, 2) == (64, 64, 128, 96)
    assert ec._cell_box(2, 5) == (128, 160, 192, 192)
    # Out-of-range cells clamp to None.
    assert ec._cell_box(3, 0) is None


def test_editor_split_partial_edge_cell(qapp):
    from tilepacker.gui_app.editor_canvas import EditorCanvas

    ec = EditorCanvas()
    ec.resize(400, 400)
    # 100x100 with a 64x32 grid: last column/row is a partial cell.
    ec.set_image(Image.new("RGBA", (100, 100), (1, 2, 3, 255)))
    ec.set_split_mode(True, 64, 32)
    assert ec._cell_box(1, 0) == (64, 0, 100, 32)   # clamped to width 100
    assert ec._cell_box(0, 3) == (0, 96, 64, 100)   # clamped to height 100


def test_editor_split_disabled_has_no_dims(qapp):
    from tilepacker.gui_app.editor_canvas import EditorCanvas

    ec = EditorCanvas()
    ec.resize(400, 400)
    ec.set_image(Image.new("RGBA", (64, 32), (1, 2, 3, 255)))
    # Off by default.
    assert ec._split_mode is False
    ec.set_split_mode(False, 64, 32)
    assert ec._split_grid_dims() is None


def test_editor_split_cell_picked_signal(qapp):
    from PySide6 import QtCore, QtGui
    from tilepacker.gui_app.editor_canvas import EditorCanvas

    ec = EditorCanvas()
    ec.resize(400, 400)
    ec.set_image(Image.new("RGBA", (192, 192), (1, 2, 3, 255)))
    ec.set_split_mode(True, 64, 32)
    # Compute the draw rect so the click can be mapped to a cell.
    ec._draw_rect = ec._compute_draw_rect()

    picked = []
    ec.cell_picked.connect(lambda box: picked.append(box))

    # A plain click (press + release at the same spot) on cell (1, 2) —
    # image px (96, 80) — adds that one cell immediately.
    draw = ec._draw_rect
    scale = draw.width() / 192
    wx = draw.left() + 96 * scale
    wy = draw.top() + 80 * scale
    pt = QtCore.QPointF(wx, wy)

    def _mouse(kind):
        return QtGui.QMouseEvent(
            kind, pt,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    ec.mousePressEvent(_mouse(QtCore.QEvent.Type.MouseButtonPress))
    ec.mouseReleaseEvent(_mouse(QtCore.QEvent.Type.MouseButtonRelease))
    assert picked == [(64, 64, 128, 96)]


# --------------------------------------------------------------------------
# PreviewCanvas paste arming
# --------------------------------------------------------------------------
def test_preview_paste_armed_and_signal(qapp):
    from tilepacker.gui_app.preview_canvas import PreviewCanvas

    pc = PreviewCanvas()
    assert pc._paste_armed is False
    pc.set_paste_armed(True)
    assert pc._paste_armed is True

    got = []
    pc.paste_at_requested.connect(lambda i: got.append(i))
    pc.paste_at_requested.emit(3)
    assert got == [3]


# --------------------------------------------------------------------------
# MainWindow: left-click a split cell adds ONLY that cell (not the whole source)
# --------------------------------------------------------------------------
def test_left_click_adds_single_cell_not_whole_source(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.import_images([_sheet_png(tmp_path)], notify=False)  # 192x192 source
    win.tile_list.setCurrentRow(0)
    win.split_w_spin.setValue(64)
    win.split_h_spin.setValue(32)
    win.split_toggle.setChecked(True)
    assert win.editor_canvas._split_mode is True

    # Left-click the cell at (col=1, row=2).
    win._on_cell_picked((64, 64, 128, 96))
    ts = win.model.tileset_tiles()
    assert len(ts) == 1
    assert ts[0].edit.crop == (64, 64, 128, 96)
    # Crucial: the tileset tile is a single 64x32 cell, NOT the 192x192 source.
    assert ts[0].render(win.model.grid).size == (64, 32)
    # The source itself is not pulled into the tileset.
    assert win.model.tiles[0].in_tileset is False
    # The added cell keeps the original source path (workspace-safe).
    assert ts[0].path == win.model.tiles[0].path
    # The source stays selected so more cells can be picked.
    assert win._current_tile() is win.model.tiles[0]

    # Clicking another cell adds another single cell.
    win._on_cell_picked((0, 0, 64, 32))
    ts = win.model.tileset_tiles()
    assert len(ts) == 2
    assert ts[1].edit.crop == (0, 0, 64, 32)


def test_right_click_add_cell_menu_path(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.import_images([_sheet_png(tmp_path)], notify=False)
    win.tile_list.setCurrentRow(0)
    win.split_toggle.setChecked(True)
    # The cell menu's "Add this cell to Tileset" action goes through here.
    win._add_cell_to_tileset((128, 160, 192, 192))
    ts = win.model.tileset_tiles()
    assert len(ts) == 1
    assert ts[0].edit.crop == (128, 160, 192, 192)
    assert ts[0].render(win.model.grid).size == (64, 32)


def test_copy_cell_then_paste_at_specific_position(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.import_images([_sheet_png(tmp_path)], notify=False)
    win.tile_list.setCurrentRow(0)
    # Put the source itself into the tileset so there is an existing tile.
    win.model.tiles[0].in_tileset = True
    win.model.commit()
    win._refresh_preview()

    win.split_toggle.setChecked(True)
    # Copy (not add) a cell, then paste it BEFORE the existing tileset tile.
    win._copy_cell((0, 0, 64, 32))
    assert win.preview_canvas._paste_armed is True
    win._on_preview_paste_at(0)
    ts = win.model.tileset_tiles()
    assert len(ts) == 2
    # The pasted cell (crop set) comes first; the original (no crop) second.
    assert ts[0].edit.crop == (0, 0, 64, 32)
    assert ts[1].edit.crop is None


def test_main_window_split_requires_selection(qapp):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    # No tiles imported: toggling split should refuse and stay off.
    win.split_toggle.setChecked(True)
    assert win.split_toggle.isChecked() is False
    assert win.editor_canvas._split_mode is False


def test_main_window_paste_survives_workspace_roundtrip(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.import_images([_sheet_png(tmp_path)], notify=False)
    win.tile_list.setCurrentRow(0)
    win.split_toggle.setChecked(True)
    win._on_cell_picked((64, 64, 128, 96))   # left-click adds the cell

    ws = tmp_path / "ws.json"
    win.save_workspace(str(ws), notify=False)

    win2 = MainWindow()
    win2.open_workspace(str(ws), notify=False)
    ts = win2.model.tileset_tiles()
    assert len(ts) == 1
    # The pasted cell is reproduced from the original source + crop.
    assert ts[0].edit.crop == (64, 64, 128, 96)
    assert ts[0].render(win2.model.grid).size == (64, 32)
