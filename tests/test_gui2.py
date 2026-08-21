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


def _field_min_alpha(cell_w, cell_h, span=5, **mask_kw):
    """Composite a field of adjacent diamond masks; return the interior minimum.

    Lays every lattice cell over a canvas the way the tileset preview and a
    Tiled isometric map do, accumulating "source over" opacity, then reports
    the lowest alpha (0-255) inside the region that is fully surrounded by
    neighbours. 255 means the tiles meet with no seam whatsoever.
    """
    mask = isogrid.diamond_mask(cell_w, cell_h, **mask_kw)
    px = mask.load()
    hw, hh = cell_w // 2, cell_h // 2
    pad_x, pad_y = cell_w * 2, cell_h * 2
    width = cell_w * span + 2 * pad_x
    height = cell_h * span + 2 * pad_y
    # Transmittance per pixel: the product of (1 - alpha) over every tile.
    inv = [[1.0] * width for _ in range(height)]
    for a in range(-4, 2 * span + 4):
        for b in range(-4, 4 * span + 4):
            if (a + b) % 2:
                continue
            left, top = a * hw - hw + pad_x, b * hh - hh + pad_y
            if left < 0 or top < 0 or left + cell_w > width or top + cell_h > height:
                continue
            for y in range(cell_h):
                row = inv[top + y]
                for x in range(cell_w):
                    value = px[x, y]
                    if value:
                        row[left + x] *= 1.0 - value / 255.0
    interior = [
        round((1.0 - inv[y][x]) * 255)
        for y in range(pad_y + cell_h, height - pad_y - cell_h)
        for x in range(pad_x + cell_w, width - pad_x - cell_w)
    ]
    return min(interior)


def test_diamond_field_has_no_translucent_seam():
    """Adjacent tiles must composite to full opacity along every shared edge.

    The regression this guards: a polygon-rasterized mask left edge pixels
    claimed by neither neighbour, so a field of tiles showed the background
    through a dotted diagonal seam. A soft edge with too little bleed fails the
    same way, just more faintly.
    """
    for cell_w, cell_h in ((16, 8), (32, 16), (24, 12)):
        assert _field_min_alpha(cell_w, cell_h) == 255, (cell_w, cell_h)


def test_antialiased_cut_needs_bleed_to_close_the_seam():
    """When antialiasing is opted into, bleed is what keeps the seam opaque.

    Two abutting 50% edges composite to 75%, leaving a translucent hairline.
    This is why antialiasing is not the default -- closing that hairline costs
    an overlap, and the overlap is what carries a neighbour's colour across.
    """
    assert _field_min_alpha(32, 16, feather=1.0, bleed=0.0) < 255
    assert _field_min_alpha(32, 16, feather=1.0, bleed=0.5) == 255


def test_diamond_mask_hard_mode_is_an_exact_partition():
    """feather=0 must claim every pixel exactly once -- no gaps, no overlaps."""
    cell_w, cell_h = 32, 16
    mask = isogrid.diamond_mask(cell_w, cell_h, feather=0.0)
    px = mask.load()
    assert set(px[x, y] for y in range(cell_h) for x in range(cell_w)) == {0, 255}
    # A hard mask covers exactly the diamond's area (half the bounding box).
    assert sum(
        1 for y in range(cell_h) for x in range(cell_w) if px[x, y]
    ) == cell_w * cell_h // 2
    # Ownership matches cell_at, which is what makes the lattice a partition.
    hw, hh = cell_w / 2.0, cell_h / 2.0
    for y in range(cell_h):
        for x in range(cell_w):
            owned = isogrid.cell_at(x + 0.5 - hw, y + 0.5 - hh, cell_w, cell_h) == (0, 0)
            assert bool(px[x, y]) == owned, (x, y)


def test_default_cut_is_hard_so_the_lattice_stays_a_partition():
    """The shipped default must be the hard cut, with no partial alpha at all.

    A soft edge cannot be an exact partition: it either leaves a translucent
    seam or overlaps its neighbour. Consumers that draw tiles with
    nearest-neighbour sampling cannot undo a soft edge baked into the PNG.
    """
    assert isogrid.DEFAULT_FEATHER == 0.0
    mask = isogrid.diamond_mask(64, 32)
    assert set(mask.getdata()) == {0, 255}
    assert sum(1 for v in mask.getdata() if v) == 64 * 32 // 2


def test_antialiasing_is_available_when_asked_for():
    mask = isogrid.diamond_mask(64, 32, feather=1.0, bleed=0.5)
    assert any(0 < v < 255 for v in mask.getdata())


def test_cell_image_keeps_rgb_on_partially_transparent_edge():
    """Masking must touch alpha only; RGB stays put.

    Compositing the crop onto a transparent canvas would scale RGB by the mask,
    pulling soft edge pixels toward black and leaving a dark fringe.
    """
    src = Image.new("RGBA", (256, 128), (120, 200, 90, 255))
    img = isogrid.cell_image(src, 2, 2, 64, 32, feather=1.0, bleed=0.5)
    assert img is not None
    soft = [px for px in img.getdata() if 0 < px[3] < 255]
    assert soft, "expected an antialiased edge"
    assert all(px[:3] == (120, 200, 90) for px in soft)


def _lattice_checker(cell_w=64, cell_h=32, size=512):
    """A source in which every lattice diamond is a flat, distinct colour."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            a, b = isogrid.cell_at(x + 0.5, y + 0.5, cell_w, cell_h)
            px[x, y] = (255, 0, 0) if (a // 2 + b // 2) % 2 == 0 else (0, 0, 255)
    return img.convert("RGBA")


def test_cut_tile_never_shows_a_neighbours_colour():
    """No visible pixel may carry the colour of the tile next to it in the source.

    The regression this guards: an antialiased edge that reaches past the
    diamond paints pixels whose RGB came from the *neighbouring* tile. They
    look harmless in place -- the neighbour is right there -- but the whole
    point of a tileset is rearranging tiles, and then that rim is a stripe of
    the wrong colour. Alpha-only checks cannot see this at all.
    """
    src = _lattice_checker()
    img = isogrid.cell_image(src, 8, 8, 64, 32)
    assert img is not None
    own = img.getpixel((32, 16))[:3]
    visible = [px[:3] for px in img.getdata() if px[3] > 0]
    assert visible, "expected an opaque interior"
    assert all(colour == own for colour in visible), "a neighbour's colour leaked in"


def test_cut_tile_bleeds_its_own_colour_just_outside_the_diamond():
    """Just outside the cut, RGB must be the tile's own colour, not the neighbour's.

    These pixels are invisible (alpha 0), but smoothing, mipmaps and border
    extrusion all sample them, so leaving the neighbour's colour there paints
    the rim wrong at render time.
    """
    src = _lattice_checker()
    img = isogrid.cell_image(src, 8, 8, 64, 32)
    assert img is not None
    own = img.getpixel((32, 16))[:3]
    # The pixel just past the left vertex of the diamond is outside the cut.
    outside = img.getpixel((0, 16))
    assert outside[3] == 0, "this pixel should be fully transparent"
    assert outside[:3] == own, "transparent border should hold the tile's own colour"


def test_cell_box_is_exactly_one_cell_for_odd_sizes():
    box = isogrid.cell_box(3, 3, 65, 33, 400, 400)
    assert box is not None
    left, top, right, bottom = box
    assert (right - left, bottom - top) == (65, 33)


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


# -- Drag the editor selection and drop it on the preview ---------------------
def test_press_on_selected_cell_arms_drag(qapp, tmp_path):
    win, ec = _editor_win(qapp, tmp_path)
    _drag(ec, _wpt(ec, 40, 64), _wpt(ec, 220, 64))
    sel = ec.selected_cells()
    assert sel
    a, b = sel[0]
    # Press on a selected cell (its centre) arms a drag-out, not a new selection.
    p = _wpt(ec, a * 32.0, b * 16.0)
    L = QtCore.Qt.MouseButton.LeftButton
    m = QtCore.Qt.KeyboardModifier.NoModifier
    ec.mousePressEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, p, L, L, m))
    assert ec._drag_candidate is True
    assert set(ec.selected_cells()) == set(sel)  # selection preserved


def test_drag_out_copies_selection(qapp, tmp_path, monkeypatch):
    from PySide6 import QtGui

    # Neutralize the blocking QDrag.exec so the flow can run headless.
    monkeypatch.setattr(QtGui.QDrag, "exec", lambda self, *a, **k: None)
    win, ec = _editor_win(qapp, tmp_path)
    _drag(ec, _wpt(ec, 40, 64), _wpt(ec, 220, 64))
    sel = ec.selected_cells()
    a, b = sel[0]
    p0 = _wpt(ec, a * 32.0, b * 16.0)
    p1 = QtCore.QPointF(p0.x() + 60, p0.y() + 60)  # move well past the threshold
    L = QtCore.Qt.MouseButton.LeftButton
    m = QtCore.Qt.KeyboardModifier.NoModifier
    ec.mousePressEvent(QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, p0, L, L, m))
    ec.mouseMoveEvent(QMouseEvent(QtCore.QEvent.Type.MouseMove, p1, L, L, m))
    # prepare_drag -> copy_selection filled the clipboard with the selection.
    assert len(win.state.clipboard) == len(sel)


def _drop(tc, pos):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QDropEvent
    from tilepacker.gui2.state import MIME_CELLS

    mime = QMimeData()
    mime.setData(MIME_CELLS, b"1")
    ev = QDropEvent(
        pos,
        QtCore.Qt.DropAction.CopyAction,
        mime,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    tc.dropEvent(ev)


def test_drop_on_empty_preview_pastes_at_origin(qapp, tmp_path):
    win, ec = _editor_win(qapp, tmp_path)
    # Select + copy an L shape, then drop onto the empty preview.
    win.state.copy_cells(
        [(0, 0, _tile((1, 0, 0, 255))), (1, 0, _tile((2, 0, 0, 255))), (0, 1, _tile((3, 0, 0, 255)))]
    )
    tc = win.tileset.canvas
    tc.resize(500, 400)
    tc.grab()
    _drop(tc, QtCore.QPointF(250, 200))
    # Empty preview -> pasted at the origin, shape preserved.
    assert set(win.state.grid.keys()) == {(0, 0), (1, 0), (0, 1)}


def test_drop_on_cell_pastes_at_that_cell(qapp, tmp_path):
    win, ec = _editor_win(qapp, tmp_path)
    # Pre-fill a 3x3 grid so the preview has geometry to hit-test.
    win.state.copy_cells([(c, r, _tile((0, 0, 0, 255))) for c in range(3) for r in range(3)])
    win.state.paste(None)
    tc = win.tileset.canvas
    tc.resize(500, 400)
    tc.grab()
    # Copy a single distinct cell, then drop it onto cell (2, 2).
    win.state.copy_cells([(9, 9, _tile((255, 0, 255, 255)))])
    base_x, base_y, scale, min_x, min_y = tc._geom
    hw, hh = 32.0, 16.0
    col, row = 2, 2
    cx = base_x + ((col - row) * hw + hw - min_x) * scale
    cy = base_y + ((col + row) * hh + hh - min_y) * scale
    _drop(tc, QtCore.QPointF(cx, cy))
    assert win.state.grid[(2, 2)].getpixel((32, 16)) == (255, 0, 255, 255)
    assert len(win.state.grid) == 9  # replaced, not added


# -- Export a tileset + isometric map (.tmx) ----------------------------------
def test_map_export_data_gids(qapp):
    st = AppState()
    st.set_cell_size(64, 32)
    for cell in [(0, 0), (1, 0), (2, 0), (0, 1), (0, 2)]:
        st._grid[cell] = _tile((0, 0, 0, 255))
    tiles, gids, cols, rows = st.map_export_data()
    assert len(tiles) == 5 and (cols, rows) == (3, 3)
    # Reading-order gids (row-major), empty cells are 0.
    assert gids == [[1, 2, 3], [4, 0, 0], [5, 0, 0]]


def test_map_export_data_normalizes_origin(qapp):
    st = AppState()
    st.set_cell_size(64, 32)
    # Cells at a non-zero origin still export as a 2x2 grid from (0,0).
    for cell in [(5, 7), (6, 7), (5, 8), (6, 8)]:
        st._grid[cell] = _tile((0, 0, 0, 255))
    tiles, gids, cols, rows = st.map_export_data()
    assert (cols, rows) == (2, 2)
    assert gids == [[1, 2], [3, 4]]


def test_export_writes_tileset_and_map(qapp, tmp_path, monkeypatch):
    win, ec = _editor_win(qapp, tmp_path)
    win.state.copy_cells([(c, r, _tile((10 * c, 100, 10 * r, 255))) for c in range(2) for r in range(2)])
    win.state.paste(None)
    out = str(tmp_path / "iso.png")
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, ""))
    )
    win._on_export()
    assert os.path.exists(out)
    assert os.path.exists(str(tmp_path / "iso.tsx"))
    tmx_path = str(tmp_path / "iso.tmx")
    assert os.path.exists(tmx_path)
    root = ET.parse(tmx_path).getroot()
    assert root.get("orientation") == "isometric"
    assert root.get("tilewidth") == "64" and root.get("tileheight") == "32"
    ts = root.find("tileset")
    assert ts.get("source") == "iso.tsx" and ts.get("firstgid") == "1"
    layer = root.find("layer")
    assert layer.get("width") == "2" and layer.get("height") == "2"
    # The 2x2 block fills every cell with gids 1..4 (row-major).
    csv = layer.find("data").text.strip().replace("\n", "").rstrip(",")
    assert sorted(int(x) for x in csv.split(",")) == [1, 2, 3, 4]


def test_build_tmx_is_valid_isometric_map():
    from tilepacker.core.tiled import build_tmx

    xml = build_tmx(
        tileset_source="t.tsx",
        columns=2,
        rows=2,
        tile_width=64,
        tile_height=32,
        gids=[[1, 0], [0, 2]],
    )
    root = ET.fromstring(xml)
    assert root.tag == "map"
    assert root.get("orientation") == "isometric"
    layer = root.find("layer")
    csv = layer.find("data").text.strip()
    assert csv == "1,0,\n0,2"


# -- Palette (.tsx) is orthogonal; map (.tmx) is isometric --------------------
def test_export_palette_is_orthogonal_map_is_isometric(qapp, tmp_path, monkeypatch):
    win, ec = _editor_win(qapp, tmp_path)
    win.state.copy_cells([(c, r, _tile((10 * c, 100, 10 * r, 255))) for c in range(2) for r in range(2)])
    win.state.paste(None)
    out = str(tmp_path / "iso.png")
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, ""))
    )
    win._on_export()
    # Palette: no <grid> element -> Tiled shows a plain square grid of tiles.
    tsx_root = ET.parse(str(tmp_path / "iso.tsx")).getroot()
    assert tsx_root.find("grid") is None
    assert tsx_root.get("tilewidth") == "64" and tsx_root.get("tileheight") == "32"
    # Map: isometric, references the .tsx.
    tmx_root = ET.parse(str(tmp_path / "iso.tmx")).getroot()
    assert tmx_root.get("orientation") == "isometric"
    assert tmx_root.find("tileset").get("source") == "iso.tsx"


def test_exported_map_gids_match_editor_layout(qapp, tmp_path, monkeypatch):
    """The .tmx gids place each tile at the same cell the editor grid had."""
    win, ec = _editor_win(qapp, tmp_path)
    # An L shape at a non-zero origin.
    for cell in [(4, 3), (5, 3), (6, 3), (4, 4), (4, 5)]:
        win.state._grid[cell] = _tile((0, 0, 0, 255))
    tiles, gids, cols, rows = win.state.map_export_data()
    out = str(tmp_path / "iso.png")
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, ""))
    )
    win._on_export()
    root = ET.parse(str(tmp_path / "iso.tmx")).getroot()
    layer = root.find("layer")
    W = int(layer.get("width"))
    H = int(layer.get("height"))
    data = [int(x) for x in layer.find("data").text.replace("\n", "").strip().strip(",").split(",")]
    grid2d = [data[y * W:(y + 1) * W] for y in range(H)]
    # Same normalized L shape: row0 full, then a left column.
    assert grid2d == [[1, 2, 3], [4, 0, 0], [5, 0, 0]]


# -- Add source images by drag & drop and clipboard paste ---------------------
def test_add_source_image_in_memory(qapp):
    st = AppState()
    st.add_source_image(_tile((1, 2, 3, 255)), "Pasted image")
    assert len(st.sources) == 1
    assert st.selected_index == 0
    assert st.sources[0].name == "Pasted image"
    assert st.selected_source().image.size == (64, 32)


def test_editor_drop_image_files_adds_sources(qapp, tmp_path):
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDropEvent

    win, ec = _editor_win(qapp, tmp_path)
    n0 = len(win.state.sources)
    p1 = _src_png(tmp_path, "d1.png")
    p2 = _src_png(tmp_path, "d2.png")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p1), QUrl.fromLocalFile(p2)])
    ev = QDropEvent(
        QPointF(50, 50),
        QtCore.Qt.DropAction.CopyAction,
        mime,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    ec.dropEvent(ev)
    assert len(win.state.sources) == n0 + 2
    assert win.state.sources[-1].name == "d2.png"


def test_editor_drop_non_image_file_ignored(qapp, tmp_path):
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDropEvent

    win, ec = _editor_win(qapp, tmp_path)
    n0 = len(win.state.sources)
    txt = tmp_path / "notes.txt"
    txt.write_text("hello")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(txt))])
    assert ec._drop_has_content(mime) is False
    ev = QDropEvent(
        QPointF(50, 50),
        QtCore.Qt.DropAction.CopyAction,
        mime,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    ec.dropEvent(ev)
    assert len(win.state.sources) == n0  # unchanged


def test_editor_drop_image_data_adds_source(qapp, tmp_path):
    from PySide6.QtCore import QMimeData, QPointF
    from PySide6.QtGui import QDropEvent
    from tilepacker.gui2.qtutil import pil_to_qimage

    win, ec = _editor_win(qapp, tmp_path)
    n0 = len(win.state.sources)
    qimg = pil_to_qimage(_tile((10, 20, 30, 255)))
    mime = QMimeData()
    mime.setImageData(qimg)
    ev = QDropEvent(
        QPointF(50, 50),
        QtCore.Qt.DropAction.CopyAction,
        mime,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    ec.dropEvent(ev)
    assert len(win.state.sources) == n0 + 1
    assert win.state.sources[-1].name == "Dropped image"


def test_paste_clipboard_image_adds_source(qapp, tmp_path):
    from tilepacker.gui2.qtutil import pil_to_qimage

    win, ec = _editor_win(qapp, tmp_path)
    n0 = len(win.state.sources)
    QtWidgets.QApplication.clipboard().setImage(pil_to_qimage(_tile((5, 5, 5, 255))))
    assert win.editor.paste_clipboard_image() is True
    assert len(win.state.sources) == n0 + 1
    assert win.state.sources[-1].name == "Pasted image"


def test_paste_image_shortcut_registered(qapp, tmp_path):
    from PySide6.QtGui import QKeySequence, QShortcut

    win, ec = _editor_win(qapp, tmp_path)
    keys = {sc.key().toString() for sc in win.findChildren(QShortcut)}
    assert QKeySequence("Ctrl+Shift+V").toString() in keys
