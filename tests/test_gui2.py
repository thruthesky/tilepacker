"""Tests for the minimal (gui2) tilepacker app.

Pure-logic tests (isogrid, state, workspace) plus headless GUI tests for the
editor drag-select/copy and the grid-based tileset preview (shape preservation,
click-anchored paste, export). Runs under the offscreen Qt platform plugin;
skipped entirely when PySide6 is absent.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

# Must be set before any QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtCore, QtWidgets  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PIL import Image  # noqa: E402

from tilepacker.gui2 import isogrid  # noqa: E402
from tilepacker.gui2.state import AppState  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def _checker(w=256, h=128, cell=16):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for y in range(h):
        for x in range(w):
            on = ((x // cell) + (y // cell)) % 2
            img.putpixel((x, y), (60, 180, 90, 255) if on else (200, 120, 40, 255))
    return img


def _src_png(tmp_path, name="src.png", w=256, h=128):
    p = tmp_path / name
    _checker(w, h).save(p, "PNG")
    return str(p)


def _tile(color):
    return Image.new("RGBA", (64, 32), color)


# -- isogrid (pure logic) -----------------------------------------------------
def test_cell_box_rejects_partial_cells():
    assert isogrid.cell_box(2, 2, 64, 32, 256, 128) is not None
    assert isogrid.cell_box(0, 0, 64, 32, 256, 128) is None


def test_cells_in_diamond_is_reading_ordered_and_2d():
    cells = isogrid.cells_in_diamond((40, 64), (220, 64), 64, 32, 256, 128)
    assert len(cells) >= 4
    xs = {(a + b) // 2 for a, b in cells}
    ys = {(b - a) // 2 for a, b in cells}
    assert len(xs) >= 2 and len(ys) >= 2
    keys = [isogrid.iso_reading_key(a, b) for a, b in cells]
    assert keys == sorted(keys)


def test_cell_image_is_diamond_masked():
    src = _checker()
    img = isogrid.cell_image(src, 2, 2, 64, 32)
    assert img is not None and img.size == (64, 32)
    assert img.getpixel((0, 0))[3] == 0
    assert img.getpixel((63, 0))[3] == 0
    assert img.getpixel((32, 16))[3] == 255


# -- AppState: sources --------------------------------------------------------
def test_state_add_remove_source(qapp, tmp_path):
    st = AppState()
    st.add_source(_src_png(tmp_path, "a.png"))
    st.add_source(_src_png(tmp_path, "b.png"))
    assert len(st.sources) == 2
    assert st.selected_index == 1
    st.remove_source(0)
    assert len(st.sources) == 1
    assert st.selected_source().name == "b.png"


# -- AppState: grid copy / paste ---------------------------------------------
def test_copy_paste_at_origin_preserves_shape(qapp):
    # An L-shaped set of cells at odd coordinates; copy normalizes to (0,0).
    items = [(3, 2, _tile((1, 0, 0, 255))), (4, 2, _tile((2, 0, 0, 255))), (3, 3, _tile((3, 0, 0, 255)))]
    st = AppState()
    st.copy_cells(items)
    assert len(st.clipboard) == 3
    # Relative coords are 0-based but keep the same shape.
    rel = {(c, r) for c, r, _ in st.clipboard}
    assert rel == {(0, 0), (1, 0), (0, 1)}
    st.paste(None)  # paste at origin
    assert set(st.grid.keys()) == {(0, 0), (1, 0), (0, 1)}


def test_paste_at_anchor_places_single_cell(qapp):
    st = AppState()
    # Pre-fill a 2x2 grid.
    st.copy_cells([(c, r, _tile((10 * (c + r), 0, 0, 255))) for c in range(2) for r in range(2)])
    st.paste(None)
    assert len(st.grid) == 4
    before = st.grid[(1, 1)]
    # Copy a single cell, then paste it onto cell (1, 1): only that cell changes.
    st.copy_cells([(5, 5, _tile((0, 255, 0, 255)))])
    assert len(st.clipboard) == 1
    st.paste((1, 1))
    assert len(st.grid) == 4  # no new cells, one replaced
    assert st.grid[(1, 1)] is not before
    assert st.grid[(1, 1)].getpixel((32, 16)) == (0, 255, 0, 255)


def test_remove_and_clear(qapp):
    st = AppState()
    st.copy_cells([(0, 0, _tile((1, 1, 1, 255))), (1, 0, _tile((2, 2, 2, 255)))])
    st.paste(None)
    assert st.remove_at((0, 0)) is True
    assert st.remove_at((9, 9)) is False
    assert len(st.grid) == 1
    st.clear_tiles()
    assert len(st.grid) == 0


def test_ordered_tiles_fills_bbox(qapp):
    st = AppState()
    # Cells (0,0) and (2,1): bbox is 3 wide x 2 tall -> 6 tiles, gaps blank.
    st.copy_cells([(0, 0, _tile((1, 0, 0, 255))), (2, 1, _tile((2, 0, 0, 255)))])
    st.paste(None)
    tiles, cols, rows = st.ordered_tiles()
    assert (cols, rows) == (3, 2)
    assert len(tiles) == 6


def test_workspace_roundtrip(qapp, tmp_path):
    st = AppState()
    st.add_source(_src_png(tmp_path))
    st.set_cell_size(48, 24)
    st.copy_cells([(0, 0, Image.new("RGBA", (48, 24), (9, 9, 9, 255))), (1, 2, Image.new("RGBA", (48, 24), (8, 8, 8, 255)))])
    st.paste(None)
    ws = str(tmp_path / "ws.json")
    st.save_workspace(ws)

    st2 = AppState()
    st2.load_workspace(ws)
    assert st2.cell_w == 48 and st2.cell_h == 24
    assert len(st2.sources) == 1
    assert set(st2.grid.keys()) == {(0, 0), (1, 2)}


# -- Editor panel (drag-select + copy preserves iso coords) -------------------
def _editor_win(qapp, tmp_path):
    from tilepacker.gui2.app import MinimalWindow

    win = MinimalWindow()
    win.resize(1000, 640)
    win.state.add_source(_src_png(tmp_path))
    win.state.set_cell_size(64, 32)
    win.editor._sync_grid()
    ec = win.editor.canvas
    ec.resize(640, 560)
    ec.grab()
    ec._draw_rect = ec._compute_draw_rect()
    return win, ec


def _wpt(ec, ix, iy):
    s = ec._scale()
    d = ec._draw_rect
    return QtCore.QPointF(d.left() + ix * s, d.top() + iy * s)


def _drag(ec, p0, p1):
    L = QtCore.Qt.MouseButton.LeftButton
    m = QtCore.Qt.KeyboardModifier.NoModifier
    ec.mousePressEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, p0, L, L, m))
    ec.mouseMoveEvent(QMouseEvent(QtCore.QEvent.Type.MouseMove, p1, L, L, m))
    ec.mouseReleaseEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonRelease, p1, L, L, m))


def test_editor_copy_then_preview_preserves_shape(qapp, tmp_path):
    win, ec = _editor_win(qapp, tmp_path)
    _drag(ec, _wpt(ec, 40, 64), _wpt(ec, 220, 64))
    sel = ec.selected_cells()
    assert len(sel) >= 4
    win.editor.copy_selection()
    n = len(win.state.clipboard)
    assert n == len(sel)

    # The clipboard's relative iso shape must match the selected cells' shape.
    cols = [(a + b) // 2 for a, b in sel]
    rows = [(b - a) // 2 for a, b in sel]
    min_c, min_r = min(cols), min(rows)
    expected = {(c - min_c, r - min_r) for c, r in zip(cols, rows)}
    got = {(c, r) for c, r, _ in win.state.clipboard}
    assert got == expected

    # Pasting at the origin reproduces exactly that shape in the grid.
    win.state.paste(None)
    assert set(win.state.grid.keys()) == expected


# -- Tileset canvas: click hit-test round-trips -------------------------------
def test_tileset_cell_click_maps_to_grid_cell(qapp):
    from tilepacker.gui2.tileset import TilesetCanvas

    tc = TilesetCanvas()
    tc.resize(500, 400)
    grid = {(c, r): _tile((20 * c, 20 * r, 0, 255)) for c in range(3) for r in range(3)}
    tc.set_grid(grid, 64, 32)
    tc.grab()  # populate paint geometry
    # Compute the widget center of cell (2, 1) and click it.
    base_x, base_y, scale, min_x, min_y = tc._geom
    hw, hh = 32.0, 16.0
    col, row = 2, 1
    cx = base_x + ((col - row) * hw + hw - min_x) * scale
    cy = base_y + ((col + row) * hh + hh - min_y) * scale
    got = tc._cell_at(QtCore.QPointF(cx, cy))
    assert got == (col, row)


def test_tileset_click_sets_anchor_and_paste_uses_it(qapp, tmp_path):
    from tilepacker.gui2.tileset import TilesetCanvas

    win, ec = _editor_win(qapp, tmp_path)
    # Build a 3x3 grid via copy/paste at origin.
    win.state.copy_cells([(c, r, _tile((0, 0, 0, 255))) for c in range(3) for r in range(3)])
    win.state.paste(None)
    tc = win.tileset.canvas
    tc.resize(500, 400)
    tc.grab()
    base_x, base_y, scale, min_x, min_y = tc._geom
    hw, hh = 32.0, 16.0
    col, row = 1, 1
    cx = base_x + ((col - row) * hw + hw - min_x) * scale
    cy = base_y + ((col + row) * hh + hh - min_y) * scale
    L = QtCore.Qt.MouseButton.LeftButton
    m = QtCore.Qt.KeyboardModifier.NoModifier
    tc.mousePressEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, QtCore.QPointF(cx, cy), L, L, m))
    assert tc.anchor() == (1, 1)

    # Copy one distinct cell; paste onto the anchor replaces exactly that cell.
    win.state.copy_cells([(7, 7, _tile((255, 0, 255, 255)))])
    win.tileset.paste_clipboard()
    assert len(win.state.grid) == 9  # unchanged count
    assert win.state.grid[(1, 1)].getpixel((32, 16)) == (255, 0, 255, 255)


# -- Export (isometric PNG + .tsx) --------------------------------------------
def test_export_writes_isometric_tsx(qapp, tmp_path):
    from tilepacker.core.config import PackConfig
    from tilepacker.core.export import export_tileset

    st = AppState()
    st.set_cell_size(64, 32)
    st.copy_cells([(c, r, _tile((20 * c, 100, 50, 255))) for c in range(3) for r in range(2)])
    st.paste(None)
    tiles, cols, rows = st.ordered_tiles()
    assert (cols, rows) == (3, 2) and len(tiles) == 6
    out = str(tmp_path / "out.png")
    res = export_tileset(
        tiles,
        PackConfig(tile_width=64, tile_height=32, columns=cols),
        out,
        write_tsx=True,
        grid_orientation="isometric",
        grid_width=64,
        grid_height=32,
    )
    assert os.path.exists(res.image_path)
    assert res.tile_count == 6 and res.columns == 3
    root = ET.parse(res.tsx_path).getroot()
    grid = root.find("grid")
    assert grid is not None
    assert grid.get("orientation") == "isometric"
    assert grid.get("width") == "64" and grid.get("height") == "32"


# -- CLI ----------------------------------------------------------------------
def test_cli_registers_gui2():
    from tilepacker.cli import build_parser

    parser = build_parser()
    ns = parser.parse_args(["gui2"])
    assert getattr(ns, "func", None) is not None


# -- Shift-click accumulation + Cmd+C / Cmd+V shortcuts -----------------------
def _click(ec, p, shift=False):
    L = QtCore.Qt.MouseButton.LeftButton
    m = (
        QtCore.Qt.KeyboardModifier.ShiftModifier
        if shift
        else QtCore.Qt.KeyboardModifier.NoModifier
    )
    ec.mousePressEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, p, L, L, m))
    ec.mouseReleaseEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonRelease, p, L, L, m))


def test_editor_shift_click_accumulates_cells(qapp, tmp_path):
    win, ec = _editor_win(qapp, tmp_path)
    # A plain click selects exactly one cell.
    _click(ec, _wpt(ec, 96, 48))
    assert len(ec.selected_cells()) == 1
    first = set(ec.selected_cells())
    # Shift-click another cell accumulates (keeps the first, adds the second).
    _click(ec, _wpt(ec, 160, 80), shift=True)
    sel = set(ec.selected_cells())
    assert len(sel) == 2
    assert first <= sel  # the first cell is still selected


def test_editor_plain_click_replaces_selection(qapp, tmp_path):
    win, ec = _editor_win(qapp, tmp_path)
    _click(ec, _wpt(ec, 96, 48))
    _click(ec, _wpt(ec, 160, 80), shift=True)
    assert len(ec.selected_cells()) == 2
    # A plain (non-Shift) click resets to a single cell.
    _click(ec, _wpt(ec, 224, 48))
    assert len(ec.selected_cells()) == 1


def test_shift_click_shape_preserved_through_copy_paste(qapp, tmp_path):
    win, ec = _editor_win(qapp, tmp_path)
    _click(ec, _wpt(ec, 96, 48))
    _click(ec, _wpt(ec, 160, 80), shift=True)
    _click(ec, _wpt(ec, 224, 48), shift=True)
    sel = ec.selected_cells()
    win.editor.copy_selection()
    cols = [(a + b) // 2 for a, b in sel]
    rows = [(b - a) // 2 for a, b in sel]
    mc, mr = min(cols), min(rows)
    expected = {(c - mc, r - mr) for c, r in zip(cols, rows)}
    win.tileset.paste_clipboard()
    assert set(win.state.grid.keys()) == expected


def test_cmd_c_and_cmd_v_shortcuts(qapp, tmp_path):
    from PySide6.QtGui import QKeySequence, QShortcut

    win, ec = _editor_win(qapp, tmp_path)
    _drag(ec, _wpt(ec, 40, 64), _wpt(ec, 220, 64))
    sel = ec.selected_cells()
    assert len(sel) >= 2

    # The window registers Cmd/Ctrl+C (copy) and Cmd/Ctrl+V (paste) shortcuts.
    copy_seq = QKeySequence(QKeySequence.StandardKey.Copy)
    paste_seq = QKeySequence(QKeySequence.StandardKey.Paste)
    by_key = {sc.key().toString(): sc for sc in win.findChildren(QShortcut)}
    assert copy_seq.toString() in by_key and paste_seq.toString() in by_key

    by_key[copy_seq.toString()].activated.emit()      # Cmd+C
    assert len(win.state.clipboard) == len(sel)
    n_before = len(win.state.grid)
    by_key[paste_seq.toString()].activated.emit()     # Cmd+V
    assert len(win.state.grid) == n_before + len(sel)


# -- Undo + delete a single cell ----------------------------------------------
def test_state_undo_restores_previous_grid(qapp):
    st = AppState()
    assert st.can_undo is False
    st.copy_cells([(0, 0, _tile((1, 0, 0, 255))), (1, 0, _tile((2, 0, 0, 255)))])
    st.paste(None)
    assert len(st.grid) == 2 and st.can_undo is True
    # Delete one cell, then undo brings it back.
    st.remove_at((0, 0))
    assert len(st.grid) == 1
    assert st.undo() is True
    assert len(st.grid) == 2
    # Undo the paste itself -> empty grid.
    assert st.undo() is True
    assert len(st.grid) == 0
    assert st.can_undo is False
    assert st.undo() is False  # nothing left


def test_state_remove_and_undo_signals(qapp):
    st = AppState()
    seen = []
    st.undo_changed.connect(lambda ok: seen.append(ok))
    st.copy_cells([(0, 0, _tile((9, 9, 9, 255)))])
    st.paste(None)                 # pushes an undo step -> True
    assert seen[-1] is True
    st.undo()                      # back to empty, no steps left -> False
    assert seen[-1] is False
    assert len(st.grid) == 0


def test_preview_delete_button_and_key_remove_anchor_cell(qapp, tmp_path):
    win, ec = _editor_win(qapp, tmp_path)
    win.state.copy_cells([(c, r, _tile((0, 0, 0, 255))) for c in range(2) for r in range(2)])
    win.state.paste(None)
    tc = win.tileset.canvas
    tc.resize(500, 400)
    tc.grab()
    # Click cell (1, 0) to make it the anchor, then delete it via the button.
    base_x, base_y, scale, min_x, min_y = tc._geom
    hw, hh = 32.0, 16.0
    col, row = 1, 0
    cx = base_x + ((col - row) * hw + hw - min_x) * scale
    cy = base_y + ((col + row) * hh + hh - min_y) * scale
    L = QtCore.Qt.MouseButton.LeftButton
    m = QtCore.Qt.KeyboardModifier.NoModifier
    tc.mousePressEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, QtCore.QPointF(cx, cy), L, L, m))
    assert tc.anchor() == (1, 0)
    assert win.tileset.delete_button.isEnabled()
    win.tileset.delete_selected()
    assert (1, 0) not in win.state.grid and len(win.state.grid) == 3

    # Undo brings the deleted cell back.
    win.state.undo()
    assert (1, 0) in win.state.grid and len(win.state.grid) == 4


def test_preview_delete_key_removes_anchor_cell(qapp, tmp_path):
    from PySide6.QtGui import QKeyEvent

    win, ec = _editor_win(qapp, tmp_path)
    win.state.copy_cells([(0, 0, _tile((0, 0, 0, 255))), (1, 0, _tile((0, 0, 0, 255)))])
    win.state.paste(None)
    tc = win.tileset.canvas
    tc.resize(500, 400)
    tc.grab()
    tc.set_anchor((0, 0))
    tc.keyPressEvent(
        QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Delete, QtCore.Qt.KeyboardModifier.NoModifier)
    )
    assert (0, 0) not in win.state.grid and len(win.state.grid) == 1


def test_cmd_z_undo_shortcut(qapp, tmp_path):
    from PySide6.QtGui import QKeySequence, QShortcut

    win, ec = _editor_win(qapp, tmp_path)
    win.state.copy_cells([(0, 0, _tile((0, 0, 0, 255)))])
    win.state.paste(None)
    assert len(win.state.grid) == 1
    undo_seq = QKeySequence(QKeySequence.StandardKey.Undo)
    by_key = {sc.key().toString(): sc for sc in win.findChildren(QShortcut)}
    assert undo_seq.toString() in by_key
    by_key[undo_seq.toString()].activated.emit()
    assert len(win.state.grid) == 0


# -- Diamond vs Rect selection shape ------------------------------------------
def test_cells_in_rect_differs_from_diamond():
    box = (40, 50, 220, 110)  # a screen rectangle
    d = set(isogrid.cells_in_diamond((box[0], box[1]), (box[2], box[3]), 64, 32, 256, 128))
    r = set(isogrid.cells_in_rect((box[0], box[1]), (box[2], box[3]), 64, 32, 256, 128))
    assert d and r and d != r
    # Every rect cell's centre lies inside the screen rectangle.
    for a, b in r:
        cx, cy = a * 32.0, b * 16.0
        assert box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def test_editor_rect_mode_uses_rect_selection(qapp, tmp_path):
    win, ec = _editor_win(qapp, tmp_path)
    p0, p1 = _wpt(ec, 40, 64), _wpt(ec, 220, 128)
    # Diamond mode (default).
    _drag(ec, p0, p1)
    diamond_sel = set(ec.selected_cells())
    # Switch to Rect via the panel combo and re-drag the same rectangle.
    idx = win.editor.shape_combo.findData("rect")
    win.editor.shape_combo.setCurrentIndex(idx)
    _drag(ec, p0, p1)
    rect_sel = set(ec.selected_cells())
    assert diamond_sel and rect_sel
    assert diamond_sel != rect_sel
    # Rect selection matches the pure-logic rect function.
    x0, y0 = ec._to_image(p0)
    x1, y1 = ec._to_image(p1)
    expected = set(isogrid.cells_in_rect((x0, y0), (x1, y1), 64, 32, ec._img_w, ec._img_h))
    assert rect_sel == expected
