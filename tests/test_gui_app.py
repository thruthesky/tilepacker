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
