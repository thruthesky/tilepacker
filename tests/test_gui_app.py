"""Headless integration tests for the PySide6 GUI.

These run under the ``offscreen`` Qt platform plugin and monkeypatch the modal
``QMessageBox`` calls (which would otherwise block forever without a display).
If PySide6 is not installed, the whole module is skipped.
"""

from __future__ import annotations

import os

# Must be set before any QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import xml.etree.ElementTree as ET

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtGui, QtWidgets  # noqa: E402
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


def _make_pngs(tmp_path, n=3, size=(100, 100)):
    colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)]
    paths = []
    for i in range(n):
        p = tmp_path / f"src{i}.png"
        Image.new("RGBA", size, colors[i % len(colors)]).save(p)
        paths.append(str(p))
    return paths


# --------------------------------------------------------------------------
# Widget construction (headless)
# --------------------------------------------------------------------------
def test_widgets_construct(qapp, tmp_path):
    from tilepacker.gui_app.editor_canvas import EditorCanvas
    from tilepacker.gui_app.preview_canvas import PreviewCanvas
    from tilepacker.gui_app.panels import GridPanel, EditPanel
    from tilepacker.gui_app.model import GridSettings, TileItem

    ec = EditorCanvas()
    ec.set_image(Image.new("RGBA", (64, 32), (10, 20, 30, 255)))
    ec.set_cell_size(128, 64)
    ec.clear()

    pc = PreviewCanvas()
    grid = GridSettings()
    gp = GridPanel(grid)
    ep = EditPanel()
    ep.set_tile(None)

    p = tmp_path / "t.png"
    Image.new("RGBA", (50, 50), (1, 2, 3, 255)).save(p)
    ep.set_tile(TileItem.load(str(p)))
    # Smoke: forcing a paint must not raise.
    pc.grab()
    ec.grab()


def test_gridpanel_writes_through(qapp):
    from tilepacker.gui_app.panels import GridPanel
    from tilepacker.gui_app.model import GridSettings

    grid = GridSettings()
    gp = GridPanel(grid)
    # tile_width is a dropdown of preset sizes (32/64/128/256).
    gp.tile_width.setCurrentText("256")
    assert grid.tile_width == 256


# --------------------------------------------------------------------------
# MainWindow import / export
# --------------------------------------------------------------------------
def test_mainwindow_import_export_isometric(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    paths = _make_pngs(tmp_path, 3)
    win.import_images(paths, notify=False)
    assert len(win.model.tiles) == 3
    assert win.model.grid.orientation == "isometric"
    assert (win.model.grid.tile_width, win.model.grid.tile_height) == (64, 32)

    # Apply a couple of edits, add the tiles to the tileset, then export.
    win.model.tiles[0].edit.rotation = 90
    win.model.tiles[0].edit.hue = 120
    win.model.tiles[1].edit.bg_remove = True
    for t in win.model.tiles:
        t.in_tileset = True

    out = tmp_path / "iso.png"
    win.export_tileset(str(out), notify=False)
    assert out.exists()
    tsx = tmp_path / "iso.tsx"
    assert tsx.exists()
    grid = ET.parse(tsx).getroot().find("grid")
    assert grid is not None and grid.get("orientation") == "isometric"


def test_mainwindow_export_orthogonal_no_grid(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.import_images(_make_pngs(tmp_path, 2), notify=False)
    win.model.grid.orientation = "orthogonal"
    win.model.grid.columns = 2
    for t in win.model.tiles:
        t.in_tileset = True
    out = tmp_path / "ortho.png"
    win.export_tileset(str(out), notify=False)
    assert out.exists()
    root = ET.parse(tmp_path / "ortho.tsx").getroot()
    assert root.find("grid") is None


def test_mainwindow_remove_and_clear(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.import_images(_make_pngs(tmp_path, 3), notify=False)
    win.model.remove(0)
    assert len(win.model.tiles) == 2
    win.model.clear()
    assert win.model.tiles == []


def test_export_empty_tileset_is_blocked(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.import_images(_make_pngs(tmp_path, 2), notify=False)
    # Imported tiles are sources only; nothing was added to the tileset, so
    # export must be blocked and write no files.
    out = tmp_path / "empty.png"
    assert win.export_tileset(str(out), notify=False) is None
    assert not out.exists()


# --------------------------------------------------------------------------
# Shortcuts / undo-redo / diamond / workspace
# --------------------------------------------------------------------------
def test_shortcuts_assigned(qapp):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    # CMD+S now saves the workspace; export moved to CMD+E.
    assert win.save_workspace_action.shortcut() == QtGui.QKeySequence(
        QtGui.QKeySequence.StandardKey.Save
    )
    assert win.export_action.shortcut() == QtGui.QKeySequence("Ctrl+E")
    assert win.open_workspace_action.shortcut() == QtGui.QKeySequence("Ctrl+Shift+O")
    assert win.undo_action.shortcut() == QtGui.QKeySequence(
        QtGui.QKeySequence.StandardKey.Undo
    )
    # Redo uses the standard Cmd+Shift+Z (no Cmd+R).
    assert win.redo_action.shortcut() == QtGui.QKeySequence("Ctrl+Shift+Z")


def test_mainwindow_undo_redo(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.import_images(_make_pngs(tmp_path, 2), notify=False)
    assert len(win.model.tiles) == 2
    win._on_undo()
    assert len(win.model.tiles) == 0
    win._on_redo()
    assert len(win.model.tiles) == 2


def test_mainwindow_diamond_signal_masks_tile(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.import_images(_make_pngs(tmp_path, 2), notify=False)
    win.tile_list.setCurrentRow(0)
    # Emulate the editor canvas emitting the 'S' key gesture.
    win.editor_canvas.diamond_requested.emit()
    assert win.model.tiles[0].edit.diamond is True
    # Undo reverts the diamond mask.
    win._on_undo()
    assert win.model.tiles[0].edit.diamond is False


def test_mainwindow_workspace_save_open_roundtrip(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.import_images(_make_pngs(tmp_path, 2), notify=False)
    win.tile_list.setCurrentRow(0)
    win._on_diamond()
    win.model.grid.tile_width = 128

    wsp = tmp_path / "ws.json"
    assert win.save_workspace(str(wsp), notify=False) is not None
    assert wsp.exists()

    win2 = MainWindow()
    assert win2.open_workspace(str(wsp), notify=False) is True
    assert len(win2.model.tiles) == 2
    assert win2.model.tiles[0].edit.diamond is True
    assert win2.model.grid.tile_width == 128
    # The grid panel must reflect the loaded grid (re-bound on open).
    assert win2.grid_panel.tile_width.currentText() == "128"


# --------------------------------------------------------------------------
# Preview <-> Edit Tile selection linking
# --------------------------------------------------------------------------
def test_preview_click_selects_tile_in_editor(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.import_images(_make_pngs(tmp_path, 3), notify=False)
    # Put tiles 0 and 2 into the tileset (tile 1 stays source-only).
    win.model.tiles[0].in_tileset = True
    win.model.tiles[2].in_tileset = True
    win.model.commit()
    win._rebuild_list()
    win._refresh_preview()

    ts = win.model.tileset_tiles()
    assert ts == [win.model.tiles[0], win.model.tiles[2]]

    # Clicking the 2nd preview tile selects the matching source row (index 2).
    win._on_preview_clicked(1)
    assert win._current_tile() is win.model.tiles[2]
    # ...and the preview highlights that tileset index.
    assert win.preview_canvas._selected == 1


def test_edit_selection_highlights_preview_only_when_in_tileset(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.import_images(_make_pngs(tmp_path, 2), notify=False)
    win.model.tiles[1].in_tileset = True
    win.model.commit()
    win._rebuild_list()
    win._refresh_preview()

    # Selecting the in-tileset tile highlights its preview cell (index 0).
    win.tile_list.setCurrentRow(1)
    assert win.preview_canvas._selected == 0
    # Selecting a source-only tile clears the preview highlight.
    win.tile_list.setCurrentRow(0)
    assert win.preview_canvas._selected is None


def test_preview_click_release_threshold(qapp):
    """A small press/release is a click (select); a large one is a drag."""
    from PySide6 import QtCore
    from tilepacker.gui_app.preview_canvas import PreviewCanvas

    pc = PreviewCanvas()
    pc._hit_rects = [(QtCore.QRectF(0, 0, 50, 50), 0), (QtCore.QRectF(60, 0, 50, 50), 1)]
    clicked, moved = [], []
    pc.tile_clicked.connect(lambda i: clicked.append(i))
    pc.tile_moved.connect(lambda a, b: moved.append((a, b)))

    def press_release(start, end):
        pc._drag_from = pc._hit_index(QtCore.QPointF(*start))
        pc._drag_hover = pc._drag_from
        pc._press_pos = QtCore.QPointF(*start)
        ev = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(*end),
            QtCore.QPointF(*end),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        pc.mouseReleaseEvent(ev)

    # Tiny move over tile 0 -> click.
    press_release((10, 10), (12, 11))
    # Big move from tile 0 to tile 1 -> reorder.
    press_release((10, 10), (80, 20))
    assert clicked == [0]
    assert moved == [(0, 1)]


# --------------------------------------------------------------------------
# Collapsible advanced sections + guided steps
# --------------------------------------------------------------------------
def test_panels_advanced_collapsed_by_default(qapp):
    from tilepacker.gui_app.panels import EditPanel, GridPanel
    from tilepacker.gui_app.model import GridSettings

    ep = EditPanel()
    assert ep.advanced_container.isHidden() is True
    ep.advanced_toggle.setChecked(True)
    assert ep.advanced_container.isHidden() is False

    gp = GridPanel(GridSettings())
    assert gp.advanced_container.isHidden() is True
    # A grid with a non-default advanced value auto-expands on bind.
    g2 = GridSettings()
    g2.margin = 4
    gp.bind(g2)
    assert gp.advanced_container.isHidden() is False


def test_step_bar_highlights_next_action(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()

    def active_step():
        for i, b in enumerate(win._step_buttons):
            if "ff7a00" in b.styleSheet():
                return i
        return None

    assert active_step() == 0                      # nothing imported -> Import
    win.import_images(_make_pngs(tmp_path, 2), notify=False)
    assert active_step() == 2                       # imported -> Add to Tileset
    win.model.tiles[0].in_tileset = True
    win.model.commit()
    win._refresh_preview()
    assert active_step() == 3                       # in tileset -> Export
