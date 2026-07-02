"""Tileset preview canvas widget for the GUI.

:class:`PreviewCanvas` paints the tiles of a :class:`ProjectModel` laid out on
the active grid, giving a quick visual sense of how the exported tileset will
look. Two layout modes are supported, selected by ``grid.fit_to_cell``:

* ``fit_to_cell == False`` (default, size-preserving): tiles keep their own
  scaled pixel size and may span several grid cells. The canvas asks the model
  for :meth:`ProjectModel.shelf_layout` and paints each ``(display_image, col,
  row)`` placement at ``(col * cell_w, row * cell_h)`` using its own size. A
  faint cell grid (``cols_cells x rows_cells``) is drawn underneath so it is
  obvious that a large tile covers multiple cells.
* ``fit_to_cell == True`` (classic uniform grid): every tile is resized into a
  single cell via :meth:`TileItem.render_cell` and arranged into
  ``grid.columns`` columns (or a near-square fallback). Orthogonal grids use a
  row-major layout; isometric grids use a 2:1 diamond projection.

The widget is intentionally a passive, read-only view rendered through
:func:`tilepacker.gui_app.qtutil.pil_to_qpixmap`. It never edits the model.

The canvas auto-fits the whole layout into the available widget area (no
scrolling); it scales down when the layout is larger than the widget. It is safe
to construct headless (offscreen) - the constructor assumes no visible window or
running event loop.

Dependencies: PySide6 + the GUI model/qtutil helpers.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from tilepacker.gui_app import qtutil
from tilepacker.gui_app.model import ProjectModel

__all__ = ["PreviewCanvas"]

#: A size-preserving placement ready to paint: pixmap plus cell coordinates.
_Placement = Tuple[QtGui.QPixmap, int, int, float, float]


class PreviewCanvas(QtWidgets.QWidget):
    """A widget that paints a tileset preview of a :class:`ProjectModel`.

    Public API:
        * :meth:`set_model` - attach (or replace) the project model to preview.
        * :meth:`refresh`   - re-read the model and request a repaint.
    """

    #: Minimum sensible size for the preview area.
    MIN_WIDTH = 360
    MIN_HEIGHT = 240

    #: Outer padding (px) kept around the laid-out tiles inside the widget.
    PADDING = 12

    #: Maximum auto-fit zoom-in factor so a small output fills the area without
    #: the pixels becoming absurdly large.
    MAX_ZOOM = 24.0

    #: Manual user zoom relative to the auto-fit scale (1.0 == auto-fit). The
    #: user can zoom further in/out with the wheel or the zoom buttons.
    MIN_USER_ZOOM = 0.2
    MAX_USER_ZOOM = 64.0
    #: Multiplicative step applied per wheel notch / zoom-button click.
    WHEEL_ZOOM_STEP = 1.2

    #: Placeholder shown when there is nothing to preview.
    PLACEHOLDER_TEXT = "Import images to preview"

    #: Background fill behind the laid-out tiles.
    BACKGROUND = QtGui.QColor("#2b2b2b")
    #: Faint cell grid line color.
    GRID_COLOR = QtGui.QColor(255, 255, 255, 28)
    #: Slightly stronger color used to highlight each tile's own bounds.
    TILE_OUTLINE_COLOR = QtGui.QColor(120, 200, 255, 110)
    #: Placeholder text color.
    PLACEHOLDER_COLOR = QtGui.QColor("#aaaaaa")
    #: Outline / fill used to mark the currently selected tile (links the
    #: preview to the Edit Tile selection both ways).
    SELECTED_COLOR = QtGui.QColor(255, 122, 0)
    SELECTED_FILL = QtGui.QColor(255, 122, 0, 40)

    #: Pointer travel (px) below which a press-release counts as a click (select)
    #: rather than a drag (reorder).
    CLICK_THRESHOLD = 6.0

    #: Emitted when a tile is dragged to a new slot: (from_index, to_index) in
    #: tileset order. Only fired in the size-preserving shelf layout.
    tile_moved = QtCore.Signal(int, int)

    #: Emitted when a tile is clicked (not dragged): the tileset index. The main
    #: window uses this to select that tile in the Edit Tile list/canvas.
    tile_clicked = QtCore.Signal(int)

    #: Emitted when a tile alignment is picked from the right-click menu:
    #: (tileset_index, align) where align is one of model.ALIGNMENTS.
    align_requested = QtCore.Signal(int, str)

    #: Emitted to remove a tile from the tileset (right-click menu or Delete key):
    #: the tileset index. The source tile itself is kept.
    remove_requested = QtCore.Signal(int)

    #: Emitted to remove several tiles at once (Shift-drag marquee + Delete):
    #: a list of tileset indices. The source tiles themselves are kept.
    remove_many_requested = QtCore.Signal(list)

    #: Emitted to paste the copied cell at a tileset position (right-click menu).
    #: Carries the insert index in tileset order; clicking an empty area carries
    #: the current tile count (append). Only meaningful while paste is armed.
    paste_at_requested = QtCore.Signal(int)

    #: Emitted when an *empty* grid slot is left-clicked in the manual-layout
    #: mode (Rows > 0) while a cell is copied (paste armed). Carries the slot
    #: index (row-major); earlier empty slots are padded so the tile lands at
    #: that exact grid position.
    place_at_requested = QtCore.Signal(int)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        """Create an empty preview canvas (no model attached yet)."""
        super().__init__(parent)
        self._model: Optional[ProjectModel] = None
        #: Cell pixmaps used by the uniform (``fit_to_cell``) layout.
        self._cell_pixmaps: List[QtGui.QPixmap] = []
        #: Size-preserving placements (pixmap, col, row) for the shelf layout.
        self._placements: List[_Placement] = []
        #: Cell-grid extent of the shelf layout (in cells).
        self._cols_cells = 0
        self._rows_cells = 0
        #: Screen rects of shelf placements for drag hit-testing: (rect, index).
        self._hit_rects: List[Tuple[QtCore.QRectF, int]] = []
        #: Index of the tile being dragged (None when idle).
        self._drag_from: Optional[int] = None
        #: Index of the slot the dragged tile would drop into (drag highlight).
        self._drag_hover: Optional[int] = None
        #: Pointer position where the current press started (click vs drag test).
        self._press_pos: Optional[QtCore.QPointF] = None
        #: Tileset index of the highlighted (selected) tile, or None.
        self._selected: Optional[int] = None
        #: Tileset indices marked by the Shift-drag marquee (multi-select for
        #: deletion). Empty when no marquee selection is active.
        self._multi_selected: set = set()
        #: Marquee (area-select) drag state, in widget coordinates.
        self._selecting = False
        self._marquee_origin: Optional[QtCore.QPointF] = None
        self._marquee_cur: Optional[QtCore.QPointF] = None
        #: True when a cell has been copied and can be pasted via right-click.
        self._paste_armed = False
        #: Slot index the pointer pressed on when it is an empty slot (a click
        #: there places the copied cell). None unless an empty slot was pressed.
        self._pending_place: Optional[int] = None
        #: Empty slot currently under the cursor (manual-layout place highlight).
        self._hover_slot: Optional[int] = None
        #: Manual zoom factor relative to the auto-fit scale (1.0 == auto-fit).
        self._user_zoom = 1.0
        #: View pan offset (px) applied on top of the centered layout.
        self._pan = QtCore.QPointF(0.0, 0.0)
        #: Last-painted geometry ``(content_rect, layout_w, layout_h, base_scale)``
        #: so wheel / button zoom can anchor and pan correctly. None until painted.
        self._last_geom: Optional[Tuple[QtCore.QRectF, float, float, float]] = None
        #: True while panning the view by dragging an empty area.
        self._panning = False
        self._pan_start = QtCore.QPointF(0.0, 0.0)
        self._pan_at_start = QtCore.QPointF(0.0, 0.0)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        # Accept keyboard focus so the Delete key can remove the selected tile.
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        # The dark backdrop is painted in paintEvent. We deliberately do NOT set
        # a widget stylesheet here, because it would be inherited by the
        # right-click QMenu and make its text unreadable (dark on dark).

    # -- Public API -----------------------------------------------------
    def set_model(self, project_model: Optional[ProjectModel]) -> None:
        """Attach the project model to preview, then refresh.

        Args:
            project_model: The :class:`ProjectModel` to render, or ``None`` to
                clear the preview.
        """
        self._model = project_model
        self.refresh()

    def set_selected(self, index: Optional[int]) -> None:
        """Highlight the tile at ``index`` in tileset order (``None`` clears it).

        Used to mirror the Edit Tile selection: when a tile that is part of the
        tileset is selected elsewhere, its preview cell is outlined.
        """
        idx = index if (index is not None and index >= 0) else None
        if idx != self._selected:
            self._selected = idx
            self.update()

    def set_paste_armed(self, armed: bool) -> None:
        """Set whether a copied cell is available to paste (enables the menu item)."""
        self._paste_armed = bool(armed)

    def refresh(self) -> None:
        """Rebuild the cached pixmaps/placements from the model and repaint."""
        self._cell_pixmaps = []
        self._placements = []
        self._cols_cells = 0
        self._rows_cells = 0
        # Tileset indices may have shifted (tiles added/removed/reordered), so
        # drop any marquee multi-selection to avoid pointing at the wrong tiles.
        self._multi_selected = set()

        model = self._model
        if model is not None and model.tiles:
            if self._uniform_layout():
                self._cell_pixmaps = self._build_cell_pixmaps()
            else:
                self._build_shelf_placements()
        self.update()

    def _uniform_layout(self) -> bool:
        """Whether the preview uses the uniform one-tile-per-cell grid.

        True when fit-to-cell is on or a manual row count is set (Rows > 0), so
        the empty-slot placement grid shows even with fit-to-cell unchecked.
        """
        model = self._model
        if model is None:
            return False
        grid = model.grid
        fn = getattr(grid, "uniform_layout", None)
        if callable(fn):
            return bool(fn())
        return bool(getattr(grid, "fit_to_cell", False) or getattr(grid, "rows", 0) > 0)

    # -- Cache builders -------------------------------------------------
    def _build_cell_pixmaps(self) -> List[QtGui.QPixmap]:
        """Render every tile into its cell-sized pixmap (uniform layout order).

        Tiles that fail to render are skipped so a single bad tile never breaks
        the whole preview.
        """
        pixmaps: List[QtGui.QPixmap] = []
        model = self._model
        if model is None:
            return pixmaps
        grid = model.grid
        # Only the tiles added to the tileset are previewed, matching export.
        for tile in model.tileset_tiles():
            try:
                cell = tile.render_cell(grid)
                pixmaps.append(qtutil.pil_to_qpixmap(cell))
            except Exception:
                # Skip unrenderable tiles rather than aborting the preview.
                continue
        return pixmaps

    def _build_shelf_placements(self) -> None:
        """Pack size-preserving display images onto the model's cell grid."""
        model = self._model
        if model is None:
            return
        try:
            placements, cols_cells, rows_cells = model.shelf_layout()
        except Exception:
            return
        for img, col, row, off_x, off_y in placements:
            try:
                self._placements.append((qtutil.pil_to_qpixmap(img), col, row, off_x, off_y))
            except Exception:
                # Skip unrenderable tiles rather than aborting the preview.
                continue
        self._cols_cells = max(0, int(cols_cells))
        self._rows_cells = max(0, int(rows_cells))

    def _columns(self, count: int) -> int:
        """Resolve the number of columns to use for ``count`` tiles.

        Honors ``grid.columns`` when positive; otherwise falls back to a
        near-square layout (``ceil(sqrt(n))``).
        """
        model = self._model
        cols = 0
        if model is not None:
            cols = max(0, int(getattr(model.grid, "columns", 0) or 0))
        if cols <= 0:
            cols = max(1, int(math.ceil(math.sqrt(max(1, count)))))
        return max(1, cols)

    def _rows_setting(self) -> int:
        """Return the manual minimum-rows setting (0 = auto)."""
        model = self._model
        if model is None:
            return 0
        return max(0, int(getattr(model.grid, "rows", 0) or 0))

    def _grid_slot_dims(self, n: int) -> Tuple[int, int, int]:
        """Return ``(cols, rows, total_slots)`` for the uniform grid.

        Honors the manual ``rows`` setting: when > 0 at least that many rows of
        (possibly empty) slots are laid out so tiles can be placed at explicit
        positions. When 0 the grid is exactly the rows needed for ``n`` tiles.
        """
        cols = self._columns(n)
        rows_setting = self._rows_setting()
        auto_rows = int(math.ceil(n / cols)) if n else 0
        rows = max(rows_setting, auto_rows)
        if rows <= 0:
            return cols, 0, 0
        return cols, rows, cols * rows

    def _slot_is_empty(self, i: int) -> bool:
        """Return True when grid slot ``i`` holds no tile (placeholder or gap)."""
        if i < 0:
            return False
        n = len(self._cell_pixmaps)
        if i >= n:
            return True  # a trailing slot beyond the current tiles
        model = self._model
        if model is None:
            return False
        ts = model.tileset_tiles()
        return i < len(ts) and getattr(ts[i], "placeholder", False)

    # -- Painting -------------------------------------------------------
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 (Qt override)
        """Paint the preview: placeholder text, or the laid-out tiles."""
        painter = QtGui.QPainter(self)
        try:
            painter.fillRect(self.rect(), self.BACKGROUND)
            # Nearest-neighbour so zoomed-in tiles stay crisp (clear edges).
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            # Rebuilt every paint so click/drag hit-testing matches what is drawn
            # in whichever layout (shelf / orthogonal / isometric) is active.
            self._hit_rects = []

            model = self._model
            if model is None or not model.tiles:
                self._paint_placeholder(painter)
                return

            if self._uniform_layout():
                # In manual-layout mode (Rows > 0) draw the empty grid even
                # before any tile is added, so slots can be clicked to place.
                if not self._cell_pixmaps and self._rows_setting() <= 0:
                    self._paint_placeholder(painter)
                    return
                orientation = getattr(model.grid, "orientation", "orthogonal")
                if orientation == "isometric":
                    self._paint_isometric(painter)
                else:
                    self._paint_orthogonal(painter)
            else:
                if not self._placements:
                    self._paint_placeholder(painter)
                    return
                self._paint_shelf(painter)
            # Overlay the marquee multi-selection (delete targets) and the live
            # drag rectangle on top of whichever layout was drawn.
            self._paint_multi_selection(painter)
            self._paint_marquee(painter)
        finally:
            painter.end()

    def _paint_placeholder(self, painter: QtGui.QPainter) -> None:
        """Draw the centered placeholder text on an empty canvas."""
        painter.setPen(self.PLACEHOLDER_COLOR)
        painter.drawText(
            self.rect(),
            int(QtCore.Qt.AlignmentFlag.AlignCenter),
            self.PLACEHOLDER_TEXT,
        )

    def _content_rect(self) -> QtCore.QRectF:
        """Return the drawable area inside the widget padding."""
        pad = self.PADDING
        return QtCore.QRectF(
            pad,
            pad,
            max(1.0, self.width() - 2 * pad),
            max(1.0, self.height() - 2 * pad),
        )

    def _fit(
        self, layout_w: float, layout_h: float
    ) -> Tuple[float, float, float]:
        """Fit ``layout_w x layout_h`` into the content rect with user zoom/pan.

        The base auto-fit scale fills the padded content area (zoomed in if
        small, capped by ``MAX_ZOOM``). The user's manual zoom (``_user_zoom``,
        1.0 == auto-fit) and pan offset are then applied on top, so the view can
        be zoomed in past the auto-fit and panned around.

        Returns:
            ``(origin_x, origin_y, scale)`` for drawing the layout.
        """
        content = self._content_rect()
        layout_w = max(1.0, layout_w)
        layout_h = max(1.0, layout_h)
        base = min(content.width() / layout_w, content.height() / layout_h)
        base = max(1e-6, min(base, self.MAX_ZOOM))
        # Remember geometry so wheel/button zoom can anchor against the layout.
        self._last_geom = (content, layout_w, layout_h, base)
        scale = base * self._user_zoom
        origin_x = content.x() + (content.width() - layout_w * scale) / 2.0 + self._pan.x()
        origin_y = content.y() + (content.height() - layout_h * scale) / 2.0 + self._pan.y()
        return origin_x, origin_y, scale

    # -- Zoom & pan -----------------------------------------------------
    def reset_view(self) -> None:
        """Reset the manual zoom and pan back to the auto-fit view."""
        self._user_zoom = 1.0
        self._pan = QtCore.QPointF(0.0, 0.0)
        self.update()

    def zoom_in(self) -> None:
        """Zoom in one step, anchored at the widget center."""
        self._zoom_at(self._center_pos(), self.WHEEL_ZOOM_STEP)

    def zoom_out(self) -> None:
        """Zoom out one step, anchored at the widget center."""
        self._zoom_at(self._center_pos(), 1.0 / self.WHEEL_ZOOM_STEP)

    def _center_pos(self) -> QtCore.QPointF:
        """Return the center of the padded content rect (zoom anchor default)."""
        r = self._content_rect()
        return QtCore.QPointF(r.x() + r.width() / 2.0, r.y() + r.height() / 2.0)

    def _zoom_at(self, pos: QtCore.QPointF, factor: float) -> None:
        """Multiply the user zoom by ``factor`` keeping ``pos`` over the same pixel.

        The layout point currently under ``pos`` stays under ``pos`` after the
        zoom (anchored zoom), which feels natural for wheel zooming.
        """
        if self._last_geom is None:
            return
        content, lw, lh, base = self._last_geom
        old_scale = base * self._user_zoom
        if old_scale <= 0:
            return
        old_ox = content.x() + (content.width() - lw * old_scale) / 2.0 + self._pan.x()
        old_oy = content.y() + (content.height() - lh * old_scale) / 2.0 + self._pan.y()
        # Layout coordinate currently under the anchor point.
        cx = (pos.x() - old_ox) / old_scale
        cy = (pos.y() - old_oy) / old_scale
        new_zoom = max(self.MIN_USER_ZOOM, min(self.MAX_USER_ZOOM, self._user_zoom * factor))
        if new_zoom == self._user_zoom:
            return
        new_scale = base * new_zoom
        # Solve the new pan so (cx, cy) still maps to pos.
        pan_x = pos.x() - content.x() - (content.width() - lw * new_scale) / 2.0 - cx * new_scale
        pan_y = pos.y() - content.y() - (content.height() - lh * new_scale) / 2.0 - cy * new_scale
        self._user_zoom = new_zoom
        self._pan = QtCore.QPointF(pan_x, pan_y)
        self.update()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: N802 (Qt override)
        """Zoom the preview in/out at the cursor with the mouse wheel."""
        if self._last_geom is None:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        factor = self.WHEEL_ZOOM_STEP if delta > 0 else 1.0 / self.WHEEL_ZOOM_STEP
        self._zoom_at(event.position(), factor)
        event.accept()

    def _paint_shelf(self, painter: QtGui.QPainter) -> None:
        """Paint the size-preserving shelf layout with a cell grid underlay.

        The whole ``cols_cells x rows_cells`` cell grid is auto-fitted into the
        widget, the grid lines are drawn faintly, then each placement is painted
        at its own (scaled) pixel size starting at its cell origin so larger
        tiles visibly cover several cells.
        """
        grid = self._model.grid
        cw = max(1, int(grid.tile_width))
        ch = max(1, int(grid.tile_height))
        cols_cells = max(1, self._cols_cells)
        rows_cells = max(1, self._rows_cells)

        layout_w = cols_cells * cw
        layout_h = rows_cells * ch
        origin_x, origin_y, scale = self._fit(layout_w, layout_h)

        cell_w = cw * scale
        cell_h = ch * scale

        # Faint cell grid so it is obvious which cells each tile covers.
        grid_pen = QtGui.QPen(self.GRID_COLOR)
        grid_pen.setWidthF(1.0)
        painter.setPen(grid_pen)
        for c in range(cols_cells + 1):
            x = origin_x + c * cell_w
            painter.drawLine(
                QtCore.QPointF(x, origin_y),
                QtCore.QPointF(x, origin_y + rows_cells * cell_h),
            )
        for r in range(rows_cells + 1):
            y = origin_y + r * cell_h
            painter.drawLine(
                QtCore.QPointF(origin_x, y),
                QtCore.QPointF(origin_x + cols_cells * cell_w, y),
            )

        # Each tile is painted at its own display size (which may span cells).
        outline = QtGui.QPen(self.TILE_OUTLINE_COLOR)
        outline.setWidthF(1.0)
        drag_pen = QtGui.QPen(QtGui.QColor(255, 215, 0), 2)
        selected_pen = QtGui.QPen(self.SELECTED_COLOR, 3)
        for i, (pixmap, col, row, off_x, off_y) in enumerate(self._placements):
            x = origin_x + col * cell_w + off_x * scale
            y = origin_y + row * cell_h + off_y * scale
            w = pixmap.width() * scale
            h = pixmap.height() * scale
            target = QtCore.QRectF(x, y, max(1.0, w), max(1.0, h))
            self._hit_rects.append((target, i))
            painter.drawPixmap(target, pixmap, QtCore.QRectF(pixmap.rect()))
            if i == self._drag_from:
                painter.setPen(drag_pen)              # the tile being dragged
            elif i == self._drag_hover:
                painter.setPen(QtGui.QPen(QtGui.QColor(0, 200, 255), 3))  # drop target
            elif i == self._selected:
                painter.fillRect(target, self.SELECTED_FILL)  # selected tile
                painter.setPen(selected_pen)
            else:
                painter.setPen(outline)
            painter.drawRect(target)

    # -- Drag to reorder (size-preserving shelf layout only) ------------
    def _hit_index(self, pos: QtCore.QPointF):
        """Return the tileset index of the placement under ``pos`` (or None).

        For an isometric uniform grid the cells are diamonds whose bounding
        boxes overlap, so a plain rectangle test would pick the wrong (adjacent)
        cell. There the point is tested against each cell's diamond region
        instead, which is exact because diamonds only share edges.
        """
        if self._is_iso_uniform():
            for rect, idx in reversed(self._hit_rects):
                if self._point_in_diamond(pos, rect):
                    return idx
            return None
        for rect, idx in reversed(self._hit_rects):
            if rect.contains(pos):
                return idx
        return None

    def _cells_in_marquee(
        self, origin: Optional[QtCore.QPointF], cur: Optional[QtCore.QPointF]
    ) -> set:
        """Return the tileset indices whose cell center falls in the marquee.

        The marquee is the widget-space rectangle spanned by ``origin`` and
        ``cur``; a tile is selected when its (last-painted) cell center lies
        inside it. Empty slots are never selected. Uses the hit rects captured by
        the most recent paint, so it stays correct in every layout mode.
        """
        if origin is None or cur is None:
            return set()
        rect = QtCore.QRectF(origin, cur).normalized()
        # Empty placeholder slots only exist in the uniform layout; the shelf
        # layout registers real tiles only, so skip the empty check there.
        uniform = self._uniform_layout()
        out: set = set()
        for r, idx in self._hit_rects:
            if uniform and self._slot_is_empty(idx):
                continue
            if rect.contains(r.center()):
                out.add(idx)
        return out

    def _is_iso_uniform(self) -> bool:
        """Return True when the active layout is the isometric uniform grid."""
        model = self._model
        return bool(
            model is not None
            and self._uniform_layout()
            and getattr(model.grid, "orientation", "orthogonal") == "isometric"
        )

    @staticmethod
    def _point_in_diamond(pos: QtCore.QPointF, rect: QtCore.QRectF) -> bool:
        """Return True when ``pos`` is inside the diamond inscribed in ``rect``."""
        hw = rect.width() / 2.0
        hh = rect.height() / 2.0
        if hw <= 0 or hh <= 0:
            return False
        c = rect.center()
        return abs((pos.x() - c.x()) / hw) + abs((pos.y() - c.y()) / hh) <= 1.0

    def _nearest_index(self, pos: QtCore.QPointF):
        """Return the index of the placement whose center is closest to ``pos``.

        Used when dropping over an empty cell so the drag still moves the tile.
        """
        best = None
        best_d = None
        for rect, idx in self._hit_rects:
            c = rect.center()
            dx = c.x() - pos.x()
            dy = c.y() - pos.y()
            d = dx * dx + dy * dy
            if best_d is None or d < best_d:
                best_d = d
                best = idx
        return best

    def _drop_target(self, pos: QtCore.QPointF):
        """The drop slot under (or nearest to) ``pos``."""
        idx = self._hit_index(pos)
        return idx if idx is not None else self._nearest_index(pos)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802
        """Delete / Backspace removes the selected tile(s) from the tileset.

        A Shift-drag marquee multi-selection takes precedence: all its tiles are
        removed at once. Otherwise the single highlighted tile is removed.
        Escape clears an active marquee selection.
        """
        if event.key() == QtCore.Qt.Key.Key_Escape and self._multi_selected:
            self._multi_selected = set()
            self.update()
            event.accept()
            return
        if event.key() in (
            QtCore.Qt.Key.Key_Delete,
            QtCore.Qt.Key.Key_Backspace,
        ):
            if self._multi_selected:
                self.remove_many_requested.emit(sorted(self._multi_selected))
                event.accept()
                return
            if self._selected is not None:
                self.remove_requested.emit(self._selected)
                event.accept()
                return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        """Arm a click/drag on a tile, or start panning when on an empty area."""
        # Take focus so the Delete key targets this preview.
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            # Shift-drag starts an area (marquee) selection for bulk delete,
            # regardless of whether the press lands on a tile or empty space.
            if event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier:
                self._selecting = True
                self._marquee_origin = event.position()
                self._marquee_cur = event.position()
                self._multi_selected = self._cells_in_marquee(
                    self._marquee_origin, self._marquee_cur
                )
                self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
                self.update()
                event.accept()
                return
            idx = self._hit_index(event.position())
            if idx is not None:
                if self._slot_is_empty(idx):
                    # Empty slot: a click here places the copied cell (not a
                    # drag/reorder). Record it and resolve on release.
                    self._pending_place = idx
                    self._press_pos = event.position()
                    event.accept()
                    return
                self._drag_from = idx
                self._drag_hover = idx
                self._press_pos = event.position()
                self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
                self.update()
                event.accept()
                return
            # Empty area: drag to pan the (possibly zoomed-in) view.
            self._panning = True
            self._pan_start = event.position()
            self._pan_at_start = QtCore.QPointF(self._pan)
            self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        """Pan the view, or (while dragging a tile) highlight the drop slot."""
        if self._selecting:
            self._marquee_cur = event.position()
            self._multi_selected = self._cells_in_marquee(
                self._marquee_origin, self._marquee_cur
            )
            self.update()
            event.accept()
            return
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan = self._pan_at_start + delta
            self.update()
            event.accept()
            return
        if self._drag_from is not None:
            hover = self._drop_target(event.position())
            if hover != self._drag_hover:
                self._drag_hover = hover
                self.update()
            event.accept()
            return
        # Idle hover: highlight an empty slot to place the copied cell into.
        hover_slot = None
        if self._paste_armed:
            idx = self._hit_index(event.position())
            if idx is not None and self._slot_is_empty(idx):
                hover_slot = idx
        if hover_slot != self._hover_slot:
            self._hover_slot = hover_slot
            self.update()
        if hover_slot is not None:
            self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        """Finish a press: a small move is a click (select), a larger one a drag.

        A click emits :attr:`tile_clicked` so the tile becomes the Edit Tile
        selection. A drag emits :attr:`tile_moved` to reorder it (dropping over
        an empty cell snaps to the nearest tile slot).
        """
        if self._selecting and event.button() == QtCore.Qt.MouseButton.LeftButton:
            # Finish the marquee: keep the multi-selection so Delete can act on it.
            self._selecting = False
            self._marquee_origin = None
            self._marquee_cur = None
            self.unsetCursor()
            self.update()
            event.accept()
            return
        if self._pending_place is not None and event.button() == QtCore.Qt.MouseButton.LeftButton:
            slot = self._pending_place
            ppos = self._press_pos
            self._pending_place = None
            self._press_pos = None
            pos = event.position()
            moved = (
                abs(pos.x() - ppos.x()) + abs(pos.y() - ppos.y())
                if ppos is not None
                else 0.0
            )
            # A click (not a drag) on an empty slot places the copied cell there.
            if moved <= self.CLICK_THRESHOLD and self._paste_armed:
                self.place_at_requested.emit(slot)
            event.accept()
            return
        if self._panning and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        if self._drag_from is not None and event.button() == QtCore.Qt.MouseButton.LeftButton:
            frm = self._drag_from
            pos = event.position()
            ppos = self._press_pos
            moved = (
                abs(pos.x() - ppos.x()) + abs(pos.y() - ppos.y())
                if ppos is not None
                else 0.0
            )
            to = self._drop_target(pos)
            self._drag_from = None
            self._drag_hover = None
            self._press_pos = None
            self.unsetCursor()
            self.update()
            if moved <= self.CLICK_THRESHOLD:
                self.tile_clicked.emit(frm)        # click: select this tile
            elif to is not None and to != frm:
                self.tile_moved.emit(frm, to)      # drag: reorder
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:  # noqa: N802
        """Right-click a tile to remove/align it, or paste a copied cell here.

        With a tile under the cursor the usual remove/align actions are shown.
        When a cell has been copied (paste armed), a "Paste copied cell here"
        action is added that inserts the cell before the clicked tile, or at the
        end when the right-click lands on an empty area.
        """
        idx = self._hit_index(QtCore.QPointF(event.pos()))
        # An empty slot: offer to place the copied cell at that exact position.
        if idx is not None and self._slot_is_empty(idx):
            if not self._paste_armed:
                return
            menu = QtWidgets.QMenu(self)
            place_action = menu.addAction("Place copied cell here")
            if menu.exec(event.globalPos()) is place_action:
                self.place_at_requested.emit(idx)
            return
        # Insert position in tileset order: before the clicked tile, or append.
        insert_idx = idx if idx is not None else len(self._hit_rects)
        if idx is None and not self._paste_armed:
            return
        menu = QtWidgets.QMenu(self)
        paste_action = None
        if self._paste_armed:
            label = (
                "Paste copied cell here" if idx is not None else "Paste copied cell (append)"
            )
            paste_action = menu.addAction(label)
        remove_action = None
        actions = []
        if idx is not None:
            if paste_action is not None:
                menu.addSeparator()
            remove_action = menu.addAction("Remove from Tileset")
            menu.addSeparator()
            menu.addAction("Align: tile in cell").setEnabled(False)
            options = [
                ("Center", "center"),
                ("Left", "left"),
                ("Right", "right"),
                ("Top", "top"),
                ("Bottom", "bottom"),
                ("Top-left (default)", "topleft"),
            ]
            actions = [(menu.addAction(lbl), value) for lbl, value in options]
        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        if chosen is paste_action:
            self.paste_at_requested.emit(insert_idx)
            return
        if chosen is remove_action:
            self.remove_requested.emit(idx)
            return
        for action, value in actions:
            if action is chosen:
                self.align_requested.emit(idx, value)
                return

    # -- Marquee (area-select) overlay ----------------------------------
    @staticmethod
    def _diamond_poly(rect: QtCore.QRectF) -> QtGui.QPolygonF:
        """Return the diamond inscribed in ``rect`` (isometric cell footprint)."""
        c = rect.center()
        return QtGui.QPolygonF(
            [
                QtCore.QPointF(c.x(), rect.top()),
                QtCore.QPointF(rect.right(), c.y()),
                QtCore.QPointF(c.x(), rect.bottom()),
                QtCore.QPointF(rect.left(), c.y()),
            ]
        )

    def _paint_multi_selection(self, painter: QtGui.QPainter) -> None:
        """Highlight the marquee-selected tiles (delete targets) in red."""
        if not self._multi_selected:
            return
        painter.save()
        fill = QtGui.QColor(255, 60, 60, 70)
        pen = QtGui.QPen(QtGui.QColor(255, 70, 70), 2.5)
        painter.setPen(pen)
        painter.setBrush(fill)
        iso = self._is_iso_uniform()
        for r, idx in self._hit_rects:
            if idx not in self._multi_selected:
                continue
            if iso:
                painter.drawPolygon(self._diamond_poly(r))
            else:
                painter.drawRect(r)
        painter.restore()

    def _paint_marquee(self, painter: QtGui.QPainter) -> None:
        """Draw the live area-select drag rectangle."""
        if (
            not self._selecting
            or self._marquee_origin is None
            or self._marquee_cur is None
        ):
            return
        rect = QtCore.QRectF(self._marquee_origin, self._marquee_cur).normalized()
        painter.save()
        pen = QtGui.QPen(QtGui.QColor(255, 90, 90), 1.5)
        pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QtGui.QColor(255, 90, 90, 40))
        painter.drawRect(rect)
        painter.restore()

    def _paint_orthogonal(self, painter: QtGui.QPainter) -> None:
        """Paint a uniform, row-major grid of cells, auto-fitted to the widget.

        Every slot of the ``cols x rows`` grid is drawn (including empty slots
        in manual-layout mode), and each is registered for hit-testing so an
        empty slot can be clicked to place a copied cell.
        """
        grid = self._model.grid
        tw = max(1, int(grid.tile_width))
        th = max(1, int(grid.tile_height))
        n = len(self._cell_pixmaps)
        cols, rows, total = self._grid_slot_dims(n)
        if total <= 0:
            return

        layout_w = cols * tw
        layout_h = rows * th
        origin_x, origin_y, scale = self._fit(layout_w, layout_h)

        cell_w = tw * scale
        cell_h = th * scale
        outline = QtGui.QPen(QtGui.QColor(255, 255, 255, 40))
        outline.setWidthF(1.0)
        empty_pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 70))
        empty_pen.setWidthF(1.0)
        empty_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        selected_pen = QtGui.QPen(self.SELECTED_COLOR, 3)
        hover_pen = QtGui.QPen(QtGui.QColor(255, 215, 0), 2)

        for i in range(total):
            col = i % cols
            row = i // cols
            x = origin_x + col * cell_w
            y = origin_y + row * cell_h
            target = QtCore.QRectF(x, y, cell_w, cell_h)
            self._hit_rects.append((target, i))
            if i < n:
                pixmap = self._cell_pixmaps[i]
                painter.drawPixmap(target, pixmap, QtCore.QRectF(pixmap.rect()))
            empty = self._slot_is_empty(i)
            if empty and i == self._hover_slot and self._paste_armed:
                painter.fillRect(target, QtGui.QColor(255, 215, 0, 55))
                painter.setPen(hover_pen)
            elif not empty and i == self._selected:
                painter.fillRect(target, self.SELECTED_FILL)
                painter.setPen(selected_pen)
            elif empty:
                painter.setPen(empty_pen)
            else:
                painter.setPen(outline)
            painter.drawRect(target)

    def _paint_isometric(self, painter: QtGui.QPainter) -> None:
        """Paint a 2:1 diamond layout, auto-fitted to the widget.

        Each tile index is unpacked to ``(col, row)`` using the resolved column
        count, then projected with the standard isometric formula:

            screen_x = (col - row) * tile_width / 2
            screen_y = (col + row) * tile_height / 2

        The whole set of positions is measured first so the origin can be
        shifted to keep every tile on-canvas (no negative coordinates), and a
        uniform scale fits the bounding box into the widget.
        """
        grid = self._model.grid
        tw = max(1, int(grid.tile_width))
        th = max(1, int(grid.tile_height))
        n = len(self._cell_pixmaps)
        cols, rows, total = self._grid_slot_dims(n)
        if total <= 0:
            return

        half_w = tw / 2.0
        half_h = th / 2.0

        # First pass: compute each slot's top-left position in iso space and the
        # overall bounding box (cells span [sx, sx+tw] x [sy, sy+th]). Every slot
        # of the cols x rows grid is included so empty slots are laid out too.
        positions = []
        min_x = min_y = math.inf
        max_x = max_y = -math.inf
        for i in range(total):
            col = i % cols
            row = i // cols
            sx = (col - row) * half_w
            sy = (col + row) * half_h
            positions.append((sx, sy))
            min_x = min(min_x, sx)
            min_y = min(min_y, sy)
            max_x = max(max_x, sx + tw)
            max_y = max(max_y, sy + th)

        layout_w = max(1.0, max_x - min_x)
        layout_h = max(1.0, max_y - min_y)
        base_x, base_y, scale = self._fit(layout_w, layout_h)

        cell_w = tw * scale
        cell_h = th * scale
        outline = QtGui.QPen(QtGui.QColor(255, 255, 255, 50))
        outline.setWidthF(1.0)
        empty_pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 80))
        empty_pen.setWidthF(1.0)
        empty_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        selected_pen = QtGui.QPen(self.SELECTED_COLOR, 3)
        hover_pen = QtGui.QPen(QtGui.QColor(255, 215, 0), 2)

        for i, (sx, sy) in enumerate(positions):
            x = base_x + (sx - min_x) * scale
            y = base_y + (sy - min_y) * scale
            target = QtCore.QRectF(x, y, cell_w, cell_h)
            self._hit_rects.append((target, i))
            if i < n:
                pixmap = self._cell_pixmaps[i]
                painter.drawPixmap(target, pixmap, QtCore.QRectF(pixmap.rect()))
            # A faint diamond outline hints at the isometric cell footprint;
            # empty slots use a dashed diamond and the selected tile a bold one.
            diamond = QtGui.QPolygonF(
                [
                    QtCore.QPointF(x + cell_w / 2.0, y),
                    QtCore.QPointF(x + cell_w, y + cell_h / 2.0),
                    QtCore.QPointF(x + cell_w / 2.0, y + cell_h),
                    QtCore.QPointF(x, y + cell_h / 2.0),
                ]
            )
            empty = self._slot_is_empty(i)
            if empty and i == self._hover_slot and self._paste_armed:
                painter.setBrush(QtGui.QColor(255, 215, 0, 55))
                painter.setPen(hover_pen)
                painter.drawPolygon(diamond)
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                continue
            if not empty and i == self._selected:
                painter.setPen(selected_pen)
            elif empty:
                painter.setPen(empty_pen)
            else:
                painter.setPen(outline)
            painter.drawPolygon(diamond)
