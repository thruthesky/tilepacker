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


# --------------------------------------------------------------------------
# Preview zoom / pan
# --------------------------------------------------------------------------
def test_preview_zoom_in_out_reset(qapp):
    from PySide6 import QtCore
    from tilepacker.gui_app.preview_canvas import PreviewCanvas

    pc = PreviewCanvas()
    pc.resize(400, 400)
    pc._fit(100, 1000)  # establish _last_geom so zoom can anchor
    assert pc._user_zoom == 1.0

    pc.zoom_in()
    assert pc._user_zoom > 1.0
    z1 = pc._user_zoom

    pc.zoom_out()
    assert pc._user_zoom < z1

    for _ in range(50):
        pc.zoom_out()
    assert pc._user_zoom >= PreviewCanvas.MIN_USER_ZOOM   # clamped

    pc.reset_view()
    assert pc._user_zoom == 1.0
    assert pc._pan == QtCore.QPointF(0.0, 0.0)


def test_preview_zoom_is_anchored(qapp):
    """The layout point under the anchor stays put across a zoom step."""
    from PySide6 import QtCore
    from tilepacker.gui_app.preview_canvas import PreviewCanvas

    pc = PreviewCanvas()
    pc.resize(400, 400)
    ox, oy, scale = pc._fit(100, 1000)
    anchor = QtCore.QPointF(180.0, 220.0)
    # Layout coordinate under the anchor before zooming.
    cx_before = (anchor.x() - ox) / scale
    cy_before = (anchor.y() - oy) / scale

    pc._zoom_at(anchor, PreviewCanvas.WHEEL_ZOOM_STEP)

    ox2, oy2, scale2 = pc._fit(100, 1000)
    cx_after = (anchor.x() - ox2) / scale2
    cy_after = (anchor.y() - oy2) / scale2
    assert abs(cx_before - cx_after) < 1e-6
    assert abs(cy_before - cy_after) < 1e-6
    assert scale2 > scale


# --------------------------------------------------------------------------
# Clean up (dedup / drop-empty / sort) + folder import
# --------------------------------------------------------------------------
def test_dedup_removes_identical_tiles(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow
    from PIL import Image

    win = MainWindow()
    # Two identical reds + one green.
    p_a = tmp_path / "a.png"; Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(p_a)
    p_b = tmp_path / "b.png"; Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(p_b)
    p_c = tmp_path / "c.png"; Image.new("RGBA", (32, 32), (0, 255, 0, 255)).save(p_c)
    win.import_images([str(p_a), str(p_b), str(p_c)], notify=False)
    assert len(win.model.tiles) == 3

    win._on_dedup()
    assert len(win.model.tiles) == 2          # one red dropped
    win._on_undo()
    assert len(win.model.tiles) == 3          # batch is one undo


def test_drop_empty_removes_transparent_tiles(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow
    from PIL import Image

    win = MainWindow()
    p_full = tmp_path / "full.png"; Image.new("RGBA", (32, 32), (10, 20, 30, 255)).save(p_full)
    p_empty = tmp_path / "empty.png"; Image.new("RGBA", (32, 32), (0, 0, 0, 0)).save(p_empty)
    win.import_images([str(p_full), str(p_empty)], notify=False)

    win._on_drop_empty()
    assert len(win.model.tiles) == 1
    assert os.path.basename(win.model.tiles[0].path) == "full.png"


def test_sort_natural_order(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow
    from PIL import Image

    win = MainWindow()
    names = ["tile10.png", "tile2.png", "tile1.png"]
    paths = []
    for n in names:
        p = tmp_path / n
        Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(p)
        paths.append(str(p))
    win.import_images(paths, notify=False)

    win._on_sort("natural")
    ordered = [os.path.basename(t.path) for t in win.model.tiles]
    assert ordered == ["tile1.png", "tile2.png", "tile10.png"]

    win._on_sort("name")
    ordered = [os.path.basename(t.path) for t in win.model.tiles]
    assert ordered == ["tile1.png", "tile10.png", "tile2.png"]   # lexicographic


def test_import_folder_recursive(qapp, tmp_path):
    from tilepacker.gui_app.main_window import MainWindow
    from PIL import Image

    (tmp_path / "sub").mkdir()
    Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(tmp_path / "a.png")
    Image.new("RGBA", (16, 16), (4, 5, 6, 255)).save(tmp_path / "sub" / "b.png")
    (tmp_path / "notes.txt").write_text("ignore me")

    win = MainWindow()
    added = win.import_folder(str(tmp_path), recursive=True, notify=False)
    assert added == 2                         # txt ignored, png in sub included
    assert len(win.model.tiles) == 2


# --------------------------------------------------------------------------
# Editor edge-crop (drag a side to trim it)
# --------------------------------------------------------------------------
def _release_at(widget, x, y):
    from PySide6 import QtCore
    ev = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonRelease,
        QtCore.QPointF(x, y),
        QtCore.QPointF(x, y),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseReleaseEvent(ev)


def test_editor_edge_hit_detection(qapp):
    from PySide6 import QtCore
    from tilepacker.gui_app.editor_canvas import EditorCanvas
    from PIL import Image

    ec = EditorCanvas()
    ec.resize(400, 400)
    ec.set_image(Image.new("RGBA", (100, 100), (255, 0, 0, 255)))
    ec._draw_rect = ec._compute_draw_rect()
    d = ec._draw_rect
    assert ec._hit_edge(QtCore.QPointF(d.left(), d.center().y())) == "left"
    assert ec._hit_edge(QtCore.QPointF(d.right(), d.center().y())) == "right"
    assert ec._hit_edge(QtCore.QPointF(d.center().x(), d.top())) == "top"
    assert ec._hit_edge(QtCore.QPointF(d.center().x(), d.bottom())) == "bottom"
    # The center is not an edge.
    assert ec._hit_edge(d.center()) is None


def test_editor_edge_crop_left_emits_box(qapp):
    from PySide6 import QtCore
    from tilepacker.gui_app.editor_canvas import EditorCanvas
    from PIL import Image

    ec = EditorCanvas()
    ec.resize(400, 400)
    ec.set_image(Image.new("RGBA", (100, 100), (255, 0, 0, 255)))
    ec._draw_rect = ec._compute_draw_rect()
    d = ec._draw_rect  # fills 0,0,400,400 (scale 4)

    boxes = []
    ec.crop_selected.connect(lambda b: boxes.append(b))

    # Drag the LEFT edge to 25% across -> trims the left 25 px of a 100px tile.
    ec._crop_edge = "left"
    target_x = d.left() + d.width() * 0.25
    ec._crop_rect = ec._crop_rect_for("left", QtCore.QPointF(target_x, d.center().y()))
    _release_at(ec, target_x, d.center().y())

    assert boxes, "edge crop should emit crop_selected"
    left, top, right, bottom = boxes[0]
    assert left == 25
    assert right == 100
    assert top == 0
    assert bottom == 100


def test_editor_edge_crop_bottom_emits_box(qapp):
    from PySide6 import QtCore
    from tilepacker.gui_app.editor_canvas import EditorCanvas
    from PIL import Image

    ec = EditorCanvas()
    ec.resize(400, 400)
    ec.set_image(Image.new("RGBA", (100, 100), (0, 255, 0, 255)))
    ec._draw_rect = ec._compute_draw_rect()
    d = ec._draw_rect

    boxes = []
    ec.crop_selected.connect(lambda b: boxes.append(b))

    # Drag the BOTTOM edge up to 75% -> keeps the top 75 px.
    ec._crop_edge = "bottom"
    target_y = d.top() + d.height() * 0.75
    ec._crop_rect = ec._crop_rect_for("bottom", QtCore.QPointF(d.center().x(), target_y))
    _release_at(ec, d.center().x(), target_y)

    assert boxes
    left, top, right, bottom = boxes[0]
    assert left == 0
    assert right == 100
    assert top == 0
    assert bottom == 75


# --------------------------------------------------------------------------
# Crop coordinate composition (the "image disappears on second crop" bug)
# --------------------------------------------------------------------------
def test_compose_crop_maps_and_accumulates(qapp, tmp_path):
    from tilepacker.gui_app.model import TileItem

    p = tmp_path / "t.png"
    Image.new("RGBA", (200, 100), (255, 0, 0, 255)).save(p)
    tile = TileItem.load(str(p))

    # First crop on the full 200x100 display -> straight source coords.
    c1 = tile.compose_crop_from_display((20, 10, 180, 90), 200, 100)
    assert c1 == (20, 10, 180, 90)
    tile.edit.crop = c1

    # The display is now 160x80 (the cropped region). A second crop must compose
    # with the first, not overwrite it against the original source.
    c2 = tile.compose_crop_from_display((0, 0, 80, 80), 160, 80)
    assert c2 == (20, 10, 100, 90)        # offset by the first crop, top-left kept


def test_compose_crop_corrects_for_scale(qapp, tmp_path):
    from tilepacker.gui_app.model import TileItem

    p = tmp_path / "t.png"
    Image.new("RGBA", (100, 100), (0, 255, 0, 255)).save(p)
    tile = TileItem.load(str(p))
    tile.edit.scale = 2.0                  # display is 200x200

    box = tile.compose_crop_from_display((100, 100, 200, 200), 200, 200)
    assert box == (50, 50, 100, 100)       # scale divided out


def test_compose_crop_handles_flip(qapp, tmp_path):
    from tilepacker.gui_app.model import TileItem

    p = tmp_path / "t.png"
    Image.new("RGBA", (100, 100), (0, 0, 255, 255)).save(p)
    tile = TileItem.load(str(p))
    tile.edit.flip_h = True

    # Cropping the left 30 px of the FLIPPED view keeps the source's right 30 px.
    box = tile.compose_crop_from_display((0, 0, 30, 100), 100, 100)
    assert box == (70, 0, 100, 100)


def test_compose_crop_blocked_by_rotation_and_trim(qapp, tmp_path):
    from tilepacker.gui_app.model import TileItem

    p = tmp_path / "t.png"
    Image.new("RGBA", (100, 100), (1, 2, 3, 255)).save(p)
    tile = TileItem.load(str(p))

    tile.edit.rotation = 90
    assert tile.compose_crop_from_display((0, 0, 50, 50), 100, 100) is None
    tile.edit.rotation = 0
    tile.edit.trim = True
    assert tile.compose_crop_from_display((0, 0, 50, 50), 100, 100) is None


def test_compose_crop_flip_scale_accumulate(qapp, tmp_path):
    """Hardest case: existing crop + horizontal flip + scale, all at once."""
    from tilepacker.gui_app.model import TileItem

    p = tmp_path / "t.png"
    Image.new("RGBA", (200, 100), (1, 2, 3, 255)).save(p)
    tile = TileItem.load(str(p))
    tile.edit.crop = (40, 10, 200, 90)     # existing crop, region is 160x80
    tile.edit.flip_h = True
    tile.edit.scale = 2.0                   # display becomes 320x160

    # Crop the left 80 display px of the flipped+scaled view. Because the view is
    # flipped, that maps to the source's right side, offset by the prior crop.
    box = tile.compose_crop_from_display((0, 0, 80, 160), 320, 160)
    assert box == (160, 10, 200, 90)


def test_crop_disabled_while_rotated(qapp, tmp_path):
    """Rotation/trim must hide crop handles and block crop in the window."""
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    win.editor_canvas.resize(400, 400)
    p = tmp_path / "t.png"
    Image.new("RGBA", (100, 100), (200, 120, 40, 255)).save(p)
    win.import_images([str(p)], notify=False)
    win.tile_list.setCurrentRow(0)
    tile = win.model.tiles[0]

    # No rotation: crop is enabled, edge handles exist.
    assert win.editor_canvas._crop_enabled is True
    win.editor_canvas._draw_rect = win.editor_canvas._compute_draw_rect()
    assert win.editor_canvas._edge_hit_rects() != {}

    # Rotate the tile -> crop gets disabled, no edge handles.
    tile.edit.rotation = 30.0
    win._show_in_editor(tile)
    assert win.editor_canvas._crop_enabled is False
    assert win.editor_canvas._edge_hit_rects() == {}

    # A crop attempt while rotated is refused (crop unchanged).
    before = tile.edit.crop
    win._on_crop_selected((10, 10, 50, 50))
    assert tile.edit.crop == before


def test_repeated_crop_keeps_content(qapp, tmp_path):
    """Regression: a second crop must not wipe an already-cropped tile."""
    from tilepacker.gui_app.main_window import MainWindow

    win = MainWindow()
    p = tmp_path / "barrel.png"
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    # Put a solid block in the lower-right so we can detect if it survives.
    for x in range(150, 230):
        for y in range(150, 230):
            img.putpixel((x, y), (200, 120, 40, 255))
    img.save(p)
    win.import_images([str(p)], notify=False)
    win.tile_list.setCurrentRow(0)
    tile = win.model.tiles[0]

    # First crop keeps the lower-right region (display == 256x256).
    win._on_crop_selected((140, 140, 240, 240))
    assert tile.edit.crop == (140, 140, 240, 240)
    rendered = tile.render(win.model.grid)
    assert rendered.getbbox() is not None      # content present

    # Second crop on the now-100x100 display: trim 10 px off each side.
    win._on_crop_selected((10, 10, 90, 90))
    assert tile.edit.crop == (150, 150, 230, 230)   # composed, not overwritten
    rendered2 = tile.render(win.model.grid)
    # The block (150..230) is exactly what remains -> still fully opaque content.
    assert rendered2.getbbox() is not None
    assert rendered2.size == (80, 80)
