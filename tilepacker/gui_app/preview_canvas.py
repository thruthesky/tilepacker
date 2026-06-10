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

    #: Maximum zoom-in factor so a small output fills the area without the
    #: pixels becoming absurdly large.
    MAX_ZOOM = 24.0

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

    #: Emitted when a tile is dragged to a new slot: (from_index, to_index) in
    #: tileset order. Only fired in the size-preserving shelf layout.
    tile_moved = QtCore.Signal(int, int)

    #: Emitted when a tile alignment is picked from the right-click menu:
    #: (tileset_index, align) where align is one of model.ALIGNMENTS.
    align_requested = QtCore.Signal(int, str)

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
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.setAutoFillBackground(True)
        # A neutral dark backdrop makes transparent tiles easy to read.
        self.setStyleSheet("background-color: #2b2b2b;")

    # -- Public API -----------------------------------------------------
    def set_model(self, project_model: Optional[ProjectModel]) -> None:
        """Attach the project model to preview, then refresh.

        Args:
            project_model: The :class:`ProjectModel` to render, or ``None`` to
                clear the preview.
        """
        self._model = project_model
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the cached pixmaps/placements from the model and repaint."""
        self._cell_pixmaps = []
        self._placements = []
        self._cols_cells = 0
        self._rows_cells = 0

        model = self._model
        if model is not None and model.tiles:
            if getattr(model.grid, "fit_to_cell", False):
                self._cell_pixmaps = self._build_cell_pixmaps()
            else:
                self._build_shelf_placements()
        self.update()

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

    # -- Painting -------------------------------------------------------
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 (Qt override)
        """Paint the preview: placeholder text, or the laid-out tiles."""
        painter = QtGui.QPainter(self)
        try:
            painter.fillRect(self.rect(), self.BACKGROUND)
            # Nearest-neighbour so zoomed-in tiles stay crisp (clear edges).
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

            model = self._model
            if model is None or not model.tiles:
                self._paint_placeholder(painter)
                return

            if getattr(model.grid, "fit_to_cell", False):
                if not self._cell_pixmaps:
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
        """Auto-fit ``layout_w x layout_h`` into the content rect.

        Returns:
            ``(origin_x, origin_y, scale)`` where the scaled layout fills the
            padded content area (zoomed in if small, capped by ``MAX_ZOOM``) and
            is centered.
        """
        content = self._content_rect()
        layout_w = max(1.0, layout_w)
        layout_h = max(1.0, layout_h)
        # Fill the available area: allow zooming IN (not only shrinking) so a
        # small output is large and readable. Capped by MAX_ZOOM.
        scale = min(content.width() / layout_w, content.height() / layout_h)
        scale = max(1e-6, min(scale, self.MAX_ZOOM))
        draw_w = layout_w * scale
        draw_h = layout_h * scale
        origin_x = content.x() + (content.width() - draw_w) / 2.0
        origin_y = content.y() + (content.height() - draw_h) / 2.0
        return origin_x, origin_y, scale

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
        self._hit_rects = []
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
            else:
                painter.setPen(outline)
            painter.drawRect(target)

    # -- Drag to reorder (size-preserving shelf layout only) ------------
    def _hit_index(self, pos: QtCore.QPointF):
        """Return the tileset index of the placement under ``pos`` (or None)."""
        for rect, idx in reversed(self._hit_rects):
            if rect.contains(pos):
                return idx
        return None

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

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        """Begin dragging the tile under the cursor (shelf layout)."""
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            idx = self._hit_index(event.position())
            if idx is not None:
                self._drag_from = idx
                self._drag_hover = idx
                self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        """While dragging, highlight the slot the tile would drop into."""
        if self._drag_from is not None:
            hover = self._drop_target(event.position())
            if hover != self._drag_hover:
                self._drag_hover = hover
                self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        """Drop the dragged tile, emitting :attr:`tile_moved` to reorder it.

        Dropping over an empty cell snaps to the nearest tile slot, so the
        drag always moves the tile somewhere.
        """
        if self._drag_from is not None and event.button() == QtCore.Qt.MouseButton.LeftButton:
            frm = self._drag_from
            to = self._drop_target(event.position())
            self._drag_from = None
            self._drag_hover = None
            self.unsetCursor()
            self.update()
            if to is not None and to != frm:
                self.tile_moved.emit(frm, to)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:  # noqa: N802
        """Right-click a tile to align it within its cell span (center/edges)."""
        idx = self._hit_index(QtCore.QPointF(event.pos()))
        if idx is None:
            return
        menu = QtWidgets.QMenu(self)
        menu.addAction("Align: tile in cell").setEnabled(False)
        menu.addSeparator()
        options = [
            ("Center", "center"),
            ("Left", "left"),
            ("Right", "right"),
            ("Top", "top"),
            ("Bottom", "bottom"),
            ("Top-left (default)", "topleft"),
        ]
        actions = [(menu.addAction(label), value) for label, value in options]
        chosen = menu.exec(event.globalPos())
        for action, value in actions:
            if action is chosen:
                self.align_requested.emit(idx, value)
                return

    def _paint_orthogonal(self, painter: QtGui.QPainter) -> None:
        """Paint a uniform, row-major grid of cells, auto-fitted to the widget."""
        grid = self._model.grid
        tw = max(1, int(grid.tile_width))
        th = max(1, int(grid.tile_height))
        n = len(self._cell_pixmaps)
        cols = self._columns(n)
        rows = max(1, int(math.ceil(n / cols)))

        layout_w = cols * tw
        layout_h = rows * th
        origin_x, origin_y, scale = self._fit(layout_w, layout_h)

        cell_w = tw * scale
        cell_h = th * scale
        outline = QtGui.QPen(QtGui.QColor(255, 255, 255, 40))
        outline.setWidthF(1.0)

        for i, pixmap in enumerate(self._cell_pixmaps):
            col = i % cols
            row = i // cols
            x = origin_x + col * cell_w
            y = origin_y + row * cell_h
            target = QtCore.QRectF(x, y, cell_w, cell_h)
            painter.drawPixmap(target, pixmap, QtCore.QRectF(pixmap.rect()))
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
        cols = self._columns(n)

        half_w = tw / 2.0
        half_h = th / 2.0

        # First pass: compute each tile's top-left position in iso space and the
        # overall bounding box (tiles span [sx, sx+tw] x [sy, sy+th]).
        positions = []
        min_x = min_y = math.inf
        max_x = max_y = -math.inf
        for i in range(n):
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

        for (sx, sy), pixmap in zip(positions, self._cell_pixmaps):
            x = base_x + (sx - min_x) * scale
            y = base_y + (sy - min_y) * scale
            target = QtCore.QRectF(x, y, cell_w, cell_h)
            painter.drawPixmap(target, pixmap, QtCore.QRectF(pixmap.rect()))
            # A faint diamond outline hints at the isometric cell footprint.
            painter.setPen(outline)
            diamond = QtGui.QPolygonF(
                [
                    QtCore.QPointF(x + cell_w / 2.0, y),
                    QtCore.QPointF(x + cell_w, y + cell_h / 2.0),
                    QtCore.QPointF(x + cell_w / 2.0, y + cell_h),
                    QtCore.QPointF(x, y + cell_h / 2.0),
                ]
            )
            painter.drawPolygon(diamond)
