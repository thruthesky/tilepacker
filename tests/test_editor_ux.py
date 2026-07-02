"""Headless tests for the editor crop/zoom UX improvements.

Covers three additions that make cropping a large source practical:
  * editor canvas zoom / pan / Fit (so big images can be inspected closely);
  * a numeric crop inspector (L/T/R/B source margins) that works even with
    rotation/trim applied;
  * larger crop-handle hit areas and edge/corner hover feedback.

Run under the ``offscreen`` Qt platform plugin. Skipped if PySide6 is absent.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtCore, QtWidgets  # noqa: E402
from PIL import Image  # noqa: E402

from tilepacker.gui_app.editor_canvas import EditorCanvas  # noqa: E402
from tilepacker.gui_app.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _silence_modals(monkeypatch):
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(
            QtWidgets.QMessageBox, name, staticmethod(lambda *a, **k: None)
        )


def _png(tmp_path, size=(400, 300)):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = ((x * 3) % 256, (y * 3) % 256, 120, 255)
    p = tmp_path / "src.png"
    img.save(p, "PNG")
    return str(p)


def _win(qapp, tmp_path, size=(400, 300)):
    win = MainWindow()
    win.import_images([_png(tmp_path, size)], notify=False)
    win.tile_list.setCurrentRow(0)
    win.editor_canvas.resize(320, 320)
    win.editor_canvas.grab()  # force a paint so fit geometry exists
    return win


# -- Phase 1: editor zoom / pan / Fit -----------------------------------------
def test_editor_zoom_enlarges_and_fit_resets(qapp, tmp_path):
    win = _win(qapp, tmp_path)
    ec = win.editor_canvas
    r0 = ec._compute_draw_rect()
    ec._zoom_at(QtCore.QPointF(100, 100), ec.WHEEL_ZOOM_STEP)
    ec._zoom_at(QtCore.QPointF(100, 100), ec.WHEEL_ZOOM_STEP)
    assert ec.current_zoom() > 1.0
    assert ec._compute_draw_rect().width() > r0.width()
    ec.fit_view()
    assert ec.current_zoom() == 1.0
    assert ec._pan == QtCore.QPointF(0.0, 0.0)


def test_editor_zoom_readout(qapp, tmp_path):
    win = _win(qapp, tmp_path)
    win._on_editor_zoom_changed(2.0)
    assert win.editor_zoom_label.text() == "200%"
    win._on_editor_zoom_changed(1.0)
    assert win.editor_zoom_label.text() == "Fit"


def test_editor_set_image_resets_view_on_size_change(qapp, tmp_path):
    win = _win(qapp, tmp_path)
    ec = win.editor_canvas
    ec._zoom_at(QtCore.QPointF(80, 80), ec.WHEEL_ZOOM_STEP)
    assert ec.current_zoom() > 1.0
    # A different-size image resets to Fit.
    ec.set_image(Image.new("RGBA", (123, 99), (0, 0, 0, 255)))
    assert ec.current_zoom() == 1.0


# -- Phase 2: numeric crop inspector ------------------------------------------
def test_numeric_crop_margins_apply(qapp, tmp_path):
    win = _win(qapp, tmp_path)
    tile = win._current_tile()
    sw, sh = tile.source.size
    ep = win.edit_panel
    ep.crop_left.setValue(40)
    ep.crop_top.setValue(30)
    ep.crop_right.setValue(60)
    ep.crop_bottom.setValue(20)
    assert tile.edit.crop == (40, 30, sw - 60, sh - 20)


def test_numeric_crop_works_with_rotation(qapp, tmp_path):
    win = _win(qapp, tmp_path)
    tile = win._current_tile()
    tile.edit.rotation = 90
    win.edit_panel.set_tile(tile)
    win.edit_panel.crop_left.setValue(50)
    # Source-space crop applies even when the on-canvas gesture would be blocked.
    assert tile.edit.crop is not None and tile.edit.crop[0] == 50


def test_numeric_crop_clamps_opposite_margins(qapp, tmp_path):
    win = _win(qapp, tmp_path)
    tile = win._current_tile()
    sw, _ = tile.source.size
    ep = win.edit_panel
    ep.crop_left.setValue(sw - 3)
    ep.crop_right.setValue(sw)  # would overflow → clamp keeps >= 1px
    left, _, right, _ = tile.edit.crop
    assert right - left >= 1


def test_numeric_crop_reset(qapp, tmp_path):
    win = _win(qapp, tmp_path)
    tile = win._current_tile()
    ep = win.edit_panel
    ep.crop_left.setValue(20)
    ep._on_reset_crop()
    assert tile.edit.crop is None
    assert ep.crop_left.value() == 0 and ep.crop_right.value() == 0


def test_numeric_crop_sync_on_reselect(qapp, tmp_path):
    win = _win(qapp, tmp_path)
    tile = win._current_tile()
    sw, sh = tile.source.size
    tile.edit.crop = (11, 22, sw - 33, sh - 44)
    win.edit_panel.set_tile(tile)
    ep = win.edit_panel
    assert (ep.crop_left.value(), ep.crop_top.value(),
            ep.crop_right.value(), ep.crop_bottom.value()) == (11, 22, 33, 44)


# -- Phase 3: hit area + hover feedback ---------------------------------------
def test_crop_hit_areas_enlarged():
    assert EditorCanvas._HANDLE_SLACK >= 10
    assert EditorCanvas._EDGE_SLACK >= 12


def test_edge_and_corner_hover_state(qapp, tmp_path):
    from PySide6.QtGui import QMouseEvent

    win = _win(qapp, tmp_path)
    ec = win.editor_canvas
    d = ec._compute_draw_rect()

    def move(pt):
        ev = QMouseEvent(
            QtCore.QEvent.Type.MouseMove, pt,
            QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        ec.mouseMoveEvent(ev)

    move(QtCore.QPointF(d.left(), d.center().y()))
    assert ec._hover_edge == "left"
    move(QtCore.QPointF(d.topLeft().x(), d.topLeft().y()))
    assert ec._hover_corner == EditorCanvas._TL
    ec.leaveEvent(QtCore.QEvent(QtCore.QEvent.Type.Leave))
    assert ec._hover_edge is None and ec._hover_corner is None


def test_edge_rail_rect_spans_side(qapp, tmp_path):
    win = _win(qapp, tmp_path)
    ec = win.editor_canvas
    ec._draw_rect = ec._compute_draw_rect()
    top = ec._edge_rail_rect("top")
    left = ec._edge_rail_rect("left")
    assert top is not None and top.width() > top.height()
    assert left is not None and left.height() > left.width()


# -- Phase 4: isometric area select (marquee) ---------------------------------
def _split_win(qapp, tmp_path):
    win = _win(qapp, tmp_path, size=(512, 320))
    win.split_orient_combo.setCurrentIndex(1)  # isometric
    win.split_w_spin.setValue(128)
    win.split_h_spin.setValue(64)
    win.split_toggle.setChecked(True)
    win.editor_canvas.grab()
    win.editor_canvas._draw_rect = win.editor_canvas._compute_draw_rect()
    return win


def _drag(ec, p0, p1, mods=None):
    from PySide6.QtGui import QMouseEvent

    m = mods or QtCore.Qt.KeyboardModifier.NoModifier
    L = QtCore.Qt.MouseButton.LeftButton
    ec.mousePressEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, p0, L, L, m))
    ec.mouseMoveEvent(QMouseEvent(QtCore.QEvent.Type.MouseMove, p1, L, L, m))
    ec.mouseReleaseEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonRelease, p1, L, L, m))


def _img_pt(ec, ix, iy):
    d = ec._draw_rect
    iw, _ = ec.image_size()
    scale = d.width() / iw
    return QtCore.QPointF(d.left() + ix * scale, d.top() + iy * scale)


def test_area_select_selects_many_cells(qapp, tmp_path):
    win = _split_win(qapp, tmp_path)
    ec = win.editor_canvas
    _drag(ec, _img_pt(ec, 128, 64), _img_pt(ec, 448, 288))
    assert ec.selection_count() >= 4
    assert win.split_add_button.isEnabled()
    assert "selected" in win.split_add_button.text()
    assert win.split_copy_button.isEnabled()


def test_wide_drag_selects_2d_grid(qapp, tmp_path):
    """A wide screen-rectangle drag selects a 2D block, not a 1D diagonal row."""
    win = _split_win(qapp, tmp_path)
    ec = win.editor_canvas
    _drag(ec, _img_pt(ec, 32, 16), _img_pt(ec, 480, 300))
    cells = ec._split_selected
    cols = {a for a, _ in cells}
    rows = {b for _, b in cells}
    assert len(cols) >= 3 and len(rows) >= 3


def test_copy_selected_button_copies_block(qapp, tmp_path):
    win = _split_win(qapp, tmp_path)
    ec = win.editor_canvas
    _drag(ec, _img_pt(ec, 32, 16), _img_pt(ec, 480, 300))
    n = ec.selection_count()
    win._on_copy_selected_cells()
    assert win._copied_tiles is not None and len(win._copied_tiles) == n


def test_area_select_commit_adds_all(qapp, tmp_path):
    win = _split_win(qapp, tmp_path)
    ec = win.editor_canvas
    _drag(ec, _img_pt(ec, 128, 64), _img_pt(ec, 448, 288))
    n = ec.selection_count()
    before = len(win.model.tileset_tiles())
    ec.commit_split_selection()
    assert len(win.model.tileset_tiles()) - before == n
    assert ec.selection_count() == 0  # cleared after commit


def test_area_select_shift_adds(qapp, tmp_path):
    win = _split_win(qapp, tmp_path)
    ec = win.editor_canvas
    _drag(ec, _img_pt(ec, 128, 64), _img_pt(ec, 256, 128))
    c1 = ec.selection_count()
    _drag(ec, _img_pt(ec, 320, 160), _img_pt(ec, 448, 224),
          QtCore.Qt.KeyboardModifier.ShiftModifier)
    assert ec.selection_count() > c1


def test_single_click_still_adds_one(qapp, tmp_path):
    win = _split_win(qapp, tmp_path)
    ec = win.editor_canvas
    before = len(win.model.tileset_tiles())
    pt = _img_pt(ec, 128, 64)
    _drag(ec, pt, pt)  # press+release same spot = click
    assert len(win.model.tileset_tiles()) == before + 1


def test_select_all_and_clear(qapp, tmp_path):
    win = _split_win(qapp, tmp_path)
    ec = win.editor_canvas
    ec._select_all_cells()
    assert ec.selection_count() > 0
    ec.clear_split_selection()
    assert ec.selection_count() == 0


# -- Phase 5: multi copy / paste (TileBlock) ----------------------------------
def test_block_copy_paste(qapp, tmp_path):
    win = _split_win(qapp, tmp_path)
    ec = win.editor_canvas
    _drag(ec, _img_pt(ec, 64, 32), _img_pt(ec, 384, 256))
    n = ec.selection_count()
    assert n >= 2
    ec.cells_copied.emit(ec.selected_cell_boxes())  # Cmd/Ctrl+C
    assert win._copied_tiles is not None and len(win._copied_tiles) == n
    before = len(win.model.tileset_tiles())
    win._on_paste_tile()  # Cmd/Ctrl+V
    assert len(win.model.tileset_tiles()) - before == n


def test_single_copy_clears_block(qapp, tmp_path):
    win = _split_win(qapp, tmp_path)
    ec = win.editor_canvas
    _drag(ec, _img_pt(ec, 64, 32), _img_pt(ec, 384, 256))
    ec.cells_copied.emit(ec.selected_cell_boxes())
    assert win._copied_tiles  # block present
    # A plain single-cell click sets a single clipboard and drops the block.
    pt = _img_pt(ec, 64, 32)
    _drag(ec, pt, pt)
    assert win._copied_tiles is None
    before = len(win.model.tileset_tiles())
    win._on_paste_tile()
    assert len(win.model.tileset_tiles()) - before == 1  # single, not the block
