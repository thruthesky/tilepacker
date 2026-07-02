"""Tests for the minimal (gui2) tilepacker app.

Pure-logic tests (isogrid, state, workspace) plus headless GUI tests for the
editor drag-select/copy and the tileset preview/paste/export flow. Runs under
the offscreen Qt platform plugin; skipped entirely when PySide6 is absent.
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


# -- isogrid (pure logic) -----------------------------------------------------
def test_cell_box_rejects_partial_cells():
    # A cell fully inside the image is picked; one hanging off the edge is not.
    assert isogrid.cell_box(2, 2, 64, 32, 256, 128) is not None
    assert isogrid.cell_box(0, 0, 64, 32, 256, 128) is None  # top-left half off-image


def test_cells_in_diamond_is_reading_ordered_and_2d():
    # A horizontal drag crosses both isometric axes -> a 2-D diamond cluster.
    cells = isogrid.cells_in_diamond((40, 64), (220, 64), 64, 32, 256, 128)
    assert len(cells) >= 4
    # Spans both isometric axes (a real diamond area, not a 1-D line).
    xs = {(a + b) // 2 for a, b in cells}
    ys = {(b - a) // 2 for a, b in cells}
    assert len(xs) >= 2 and len(ys) >= 2
    # Returned in natural reading order.
    keys = [isogrid.iso_reading_key(a, b) for a, b in cells]
    assert keys == sorted(keys)


def test_cell_image_is_diamond_masked():
    src = _checker()
    img = isogrid.cell_image(src, 2, 2, 64, 32)
    assert img is not None and img.size == (64, 32)
    # Corners are outside the diamond -> transparent; the center is opaque.
    assert img.getpixel((0, 0))[3] == 0
    assert img.getpixel((63, 0))[3] == 0
    assert img.getpixel((32, 16))[3] == 255


# -- AppState -----------------------------------------------------------------
def test_state_add_remove_source(qapp, tmp_path):
    st = AppState()
    a = _src_png(tmp_path, "a.png")
    b = _src_png(tmp_path, "b.png")
    st.add_source(a)
    st.add_source(b)
    assert len(st.sources) == 2
    assert st.selected_index == 1  # newest selected
    st.remove_source(0)
    assert len(st.sources) == 1
    assert st.selected_source().name == "b.png"


def test_state_copy_paste_and_remove_tiles(qapp):
    st = AppState()
    cells = [Image.new("RGBA", (64, 32), (i, 0, 0, 255)) for i in range(3)]
    st.copy_cells(cells)
    assert len(st.clipboard) == 3
    added = st.paste()
    assert added == 3 and len(st.tiles) == 3
    st.paste()  # paste again appends
    assert len(st.tiles) == 6
    st.remove_tiles([0, 1])
    assert len(st.tiles) == 4


def test_workspace_roundtrip(qapp, tmp_path):
    st = AppState()
    st.add_source(_src_png(tmp_path))
    st.set_cell_size(48, 24)
    st.set_columns(5)
    st.copy_cells([Image.new("RGBA", (48, 24), (9, 9, 9, 255)) for _ in range(4)])
    st.paste()
    ws = str(tmp_path / "ws.json")
    st.save_workspace(ws)

    st2 = AppState()
    st2.load_workspace(ws)
    assert st2.cell_w == 48 and st2.cell_h == 24
    assert st2.columns == 5
    assert len(st2.sources) == 1
    assert len(st2.tiles) == 4


# -- Editor panel (drag-select + copy) ----------------------------------------
def _editor_win(qapp, tmp_path):
    from tilepacker.gui2.app import MinimalWindow

    win = MinimalWindow()
    win.resize(1000, 640)
    win.state.add_source(_src_png(tmp_path))
    win.state.set_cell_size(64, 32)
    win.editor._sync_grid()
    ec = win.editor.canvas
    ec.resize(640, 560)
    ec.grab()  # force a paint so _draw_rect is current
    ec._draw_rect = ec._compute_draw_rect()
    return win, ec


def _wpt(ec, ix, iy):
    s = ec._scale()
    d = ec._draw_rect
    return QtCore.QPointF(d.left() + ix * s, d.top() + iy * s)


def test_editor_drag_selects_diamond_and_copy_fills_clipboard(qapp, tmp_path):
    win, ec = _editor_win(qapp, tmp_path)
    L = QtCore.Qt.MouseButton.LeftButton
    m = QtCore.Qt.KeyboardModifier.NoModifier
    p0 = _wpt(ec, 40, 20)
    p1 = _wpt(ec, 220, 110)
    ec.mousePressEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, p0, L, L, m))
    ec.mouseMoveEvent(QMouseEvent(QtCore.QEvent.Type.MouseMove, p1, L, L, m))
    ec.mouseReleaseEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonRelease, p1, L, L, m))
    sel = ec.selected_cells()
    assert len(sel) >= 4
    assert win.editor.copy_button.isEnabled()

    win.editor._on_copy()
    assert len(win.state.clipboard) == len(sel)
    assert all(im.size == (64, 32) for im in win.state.clipboard)


# -- Tileset panel (paste + rows auto) ----------------------------------------
def test_tileset_paste_and_rows_auto(qapp, tmp_path):
    win, ec = _editor_win(qapp, tmp_path)
    L = QtCore.Qt.MouseButton.LeftButton
    m = QtCore.Qt.KeyboardModifier.NoModifier
    ec.mousePressEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, _wpt(ec, 40, 20), L, L, m))
    ec.mouseMoveEvent(QMouseEvent(QtCore.QEvent.Type.MouseMove, _wpt(ec, 220, 110), L, L, m))
    ec.mouseReleaseEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonRelease, _wpt(ec, 220, 110), L, L, m))
    win.editor._on_copy()
    n = len(win.state.clipboard)

    assert win.tileset.paste_button.isEnabled()
    win.state.paste()
    assert len(win.state.tiles) == n
    win.state.set_columns(3)
    import math

    assert win.tileset.canvas.rows() == math.ceil(n / 3)


# -- Export (isometric PNG + .tsx) --------------------------------------------
def test_export_writes_isometric_tsx(qapp, tmp_path):
    from tilepacker.core.config import PackConfig
    from tilepacker.core.export import export_tileset

    st = AppState()
    st.set_cell_size(64, 32)
    st.copy_cells([Image.new("RGBA", (64, 32), (i * 20, 100, 50, 255)) for i in range(6)])
    st.paste()
    out = str(tmp_path / "out.png")
    res = export_tileset(
        st.tiles,
        PackConfig(tile_width=64, tile_height=32, columns=4),
        out,
        write_tsx=True,
        grid_orientation="isometric",
        grid_width=64,
        grid_height=32,
    )
    assert os.path.exists(res.image_path)
    assert res.tile_count == 6 and res.columns == 4
    root = ET.parse(res.tsx_path).getroot()
    grid = root.find("grid")
    assert grid is not None
    assert grid.get("orientation") == "isometric"
    assert grid.get("width") == "64" and grid.get("height") == "32"


# -- CLI ----------------------------------------------------------------------
def test_cli_registers_gui2():
    from tilepacker.cli import build_parser

    parser = build_parser()
    # The gui2 subcommand parses without error and has a handler.
    ns = parser.parse_args(["gui2"])
    assert getattr(ns, "func", None) is not None
