"""Interactive editor canvas for a single tile's rendered result.

This widget displays the rendered result image of the currently selected tile
and offers two drag gestures, distinguished by where the press begins:

* Dragging **inside** the image draws a rubber-band rectangle to pick a crop
  region. On release the rectangle is mapped from on-screen (display)
  coordinates back to the displayed image's pixel coordinates and emitted via
  :attr:`crop_selected`.
* Dragging one of the four **corner handles** resizes the tile while preserving
  its aspect ratio. The opposite corner stays anchored; a dashed preview shows
  the new size. On release the scale *factor* (relative to the current display
  size) is emitted via :attr:`resize_requested` so the caller can multiply it
  into ``edit.scale``.
* Dragging one of the four **edge handles** (the small bars centered on each
  side) crops that side inward by the dragged amount, trimming margins. It uses
  the same crop path as the rubber-band, emitting :attr:`crop_selected` with the
  kept region in displayed-image pixel coordinates.

The image is drawn fit-to-widget (aspect ratio preserved, centered) over a
light checkerboard so transparent areas are visible. The widget never mutates
the PIL image and only relies on
:func:`tilepacker.gui_app.qtutil.pil_to_qpixmap` to render it, so it can be
constructed headless (offscreen) without an event loop.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from tilepacker.gui_app import qtutil

__all__ = ["EditorCanvas"]


class EditorCanvas(QtWidgets.QWidget):
    """Display a rendered tile image and edit it by dragging.

    Signals:
        crop_selected(tuple): Emitted on mouse release with the selected crop
            box ``(left, top, right, bottom)`` as integer pixel coordinates of
            the currently displayed image. Never emitted for a zero-area box.
        resize_requested(float): Emitted on mouse release after dragging a
            corner handle, carrying the positive scale factor (relative to the
            current display size, aspect ratio preserved). Suppressed when the
            factor is effectively 1.0.
    """

    #: Emitted with an integer ``(left, top, right, bottom)`` crop box in
    #: the displayed image's own pixel coordinate space.
    crop_selected = QtCore.Signal(tuple)

    #: Emitted with a positive ``float`` resize factor relative to the current
    #: display size (aspect ratio preserved). ``1.5`` means "make it 1.5x".
    resize_requested = QtCore.Signal(float)

    #: Emitted when the user presses ``S`` to mask the tile to the cell-ratio
    #: diamond. Carries no argument (the receiver knows the current tile/grid).
    diamond_requested = QtCore.Signal()

    #: Emitted when the user presses ``C`` to copy the current tile.
    copy_requested = QtCore.Signal()

    #: Emitted when the user presses ``P`` to paste the copied tile into the tileset.
    paste_requested = QtCore.Signal()

    #: Emitted in Grid Split mode when a grid cell is clicked. Carries the
    #: cell rectangle ``(left, top, right, bottom)`` in the displayed image's
    #: own pixel coordinates, so the caller can map it back to a source crop.
    cell_picked = QtCore.Signal(tuple)

    #: Size (in pixels) of each square of the transparency checkerboard.
    _CHECKER = 8

    #: Side length (in widget pixels) of each square corner resize handle.
    _HANDLE = 8

    #: Extra slack (in pixels) added around a handle when hit-testing, so the
    #: handle is comfortable to grab even with an imprecise click.
    _HANDLE_SLACK = 3

    #: Lower bound on the emitted resize factor; prevents collapsing a tile.
    _MIN_FACTOR = 0.05

    #: Resize factors within this distance of 1.0 are treated as "no change".
    _NOOP_EPS = 0.02

    #: Corner identifiers (index into the four-corner geometry helpers).
    _TL, _TR, _BL, _BR = 0, 1, 2, 3

    #: Side (edge) identifiers for the four edge crop handles.
    _LEFT, _TOP, _RIGHT, _BOTTOM = "left", "top", "right", "bottom"

    #: Visible length / thickness (widget px) of each side crop handle bar.
    _EDGE_BAR_LEN = 22
    _EDGE_BAR_THICK = 6

    #: Hit slack (px) on either side of an image edge for grabbing its crop handle.
    _EDGE_SLACK = 5

    #: Minimum remaining size (widget px) when cropping a side inward.
    _EDGE_MIN_GAP = 4.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QtGui.QPixmap] = None
        # Cell size (grid aspect-ratio guide); stored for potential use only.
        self._cell_width: int = 0
        self._cell_height: int = 0
        # The rectangle the image currently occupies inside the widget (device
        # independent / logical widget coordinates), recomputed every paint.
        self._draw_rect = QtCore.QRectF()
        # When True, a tile-ratio diamond *selection* outline is drawn over the
        # image. The diamond mask itself is applied only in the tileset/export.
        self._diamond_overlay = False
        # Crop (rubber-band) drag state.
        self._rubber = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Shape.Rectangle, self)
        self._drag_origin: Optional[QtCore.QPoint] = None
        # Resize drag state.
        self._resize_corner: Optional[int] = None      # which handle is held
        self._resize_anchor = QtCore.QPointF()         # fixed opposite corner
        self._resize_start = QtCore.QPointF()           # dragged corner at start
        self._resize_factor: float = 1.0                # live factor for preview
        # Edge-crop drag state.
        self._crop_edge: Optional[str] = None           # which side is dragged
        self._crop_rect = QtCore.QRectF()               # live kept region (widget)
        # Whether crop gestures (edge + rubber-band) are allowed. The window
        # disables them while rotation/trim is applied, since a crop drawn on
        # that rendered image cannot be mapped to an axis-aligned source crop.
        self._crop_enabled = True
        # Grid Split mode: when active, a ``_split_w`` x ``_split_h`` cell grid
        # is overlaid on the image and clicking a cell emits :attr:`cell_picked`
        # (so the cell can be copied out as its own tile). While it is active the
        # crop / resize / edge gestures are suspended. ``_split_hover`` is the
        # ``(col, row)`` cell under the cursor, highlighted for feedback.
        self._split_mode = False
        self._split_w = 0
        self._split_h = 0
        self._split_hover: Optional[Tuple[int, int]] = None

        self.setMinimumSize(320, 240)
        # Mouse tracking lets us swap the cursor when hovering a handle.
        self.setMouseTracking(True)
        # Strong focus so the canvas receives the 'S' key (diamond mask) once it
        # has been clicked or tabbed into.
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    # -- Public API -----------------------------------------------------
    def set_image(self, pil_image) -> None:
        """Display ``pil_image`` (a PIL image), or clear when ``None``.

        The image is converted to a ``QPixmap`` via :func:`qtutil.pil_to_qpixmap`
        and kept for painting. Passing ``None`` clears the canvas.

        Args:
            pil_image: The PIL image to show, or ``None`` to clear.
        """
        if pil_image is None:
            self.clear()
            return
        self._pixmap = qtutil.pil_to_qpixmap(pil_image)
        self._cancel_drags()
        self._split_hover = None
        self.update()

    def clear(self) -> None:
        """Clear the displayed image and cancel any active drag."""
        self._pixmap = None
        self._cancel_drags()
        self._split_hover = None
        self.unsetCursor()
        self.update()

    def image_size(self) -> Tuple[int, int]:
        """Return the displayed image's pixel size, or ``(0, 0)`` when empty.

        Used by the window to map a crop (drawn in displayed-image pixels) back
        to source coordinates.
        """
        if self._pixmap is None or self._pixmap.isNull():
            return (0, 0)
        return (self._pixmap.width(), self._pixmap.height())

    def set_crop_enabled(self, enabled: bool) -> None:
        """Allow or block crop gestures (edge handles + rubber-band).

        Corner resize is unaffected. Disabled while rotation/trim is applied so
        the user is not offered a crop that cannot be mapped back to a source
        crop (and any in-progress crop is cancelled).
        """
        enabled = bool(enabled)
        if enabled == self._crop_enabled:
            return
        self._crop_enabled = enabled
        if not enabled:
            self._crop_edge = None
            self._crop_rect = QtCore.QRectF()
            self._drag_origin = None
            self._rubber.hide()
        self.update()

    def set_cell_size(self, width: int, height: int) -> None:
        """Record the grid cell size used as an aspect-ratio guide.

        Stored for reference; it does not change how the image is fit. Provided
        so callers can drive a future cell overlay without changing this API.

        Args:
            width: Grid cell width in pixels.
            height: Grid cell height in pixels.
        """
        self._cell_width = int(width)
        self._cell_height = int(height)
        self.update()

    def set_diamond_overlay(self, active: bool) -> None:
        """Show or hide the tile-ratio diamond selection outline over the image."""
        active = bool(active)
        if active != self._diamond_overlay:
            self._diamond_overlay = active
            self.update()

    # -- Grid Split mode -----------------------------------------------
    def set_split_mode(self, active: bool, cell_w: int = 0, cell_h: int = 0) -> None:
        """Enable / disable the Grid Split overlay and set its cell size.

        When ``active`` is True a ``cell_w`` x ``cell_h`` grid is drawn over the
        image and clicking a cell emits :attr:`cell_picked`. Crop / resize / edge
        gestures are suspended while it is on. Passing a non-positive cell size
        keeps the previous size; the overlay only draws when both are positive.

        Args:
            active: Whether Grid Split mode is on.
            cell_w: Cell width in (displayed-image) pixels.
            cell_h: Cell height in (displayed-image) pixels.
        """
        if cell_w > 0:
            self._split_w = int(cell_w)
        if cell_h > 0:
            self._split_h = int(cell_h)
        active = bool(active)
        if active != self._split_mode:
            self._split_mode = active
            self._cancel_drags()
        self._split_hover = None
        self.update()

    def _split_grid_dims(self) -> Optional[Tuple[int, int, int, int]]:
        """Return ``(img_w, img_h, cell_w, cell_h)`` for the split grid, or None.

        ``None`` when split mode is off, there is no image, or the cell size is
        not positive yet.
        """
        if not self._split_mode:
            return None
        if self._pixmap is None or self._pixmap.isNull():
            return None
        sw = max(1, self._split_w)
        sh = max(1, self._split_h)
        if self._split_w <= 0 or self._split_h <= 0:
            return None
        return (self._pixmap.width(), self._pixmap.height(), sw, sh)

    def _cell_at(self, pos: QtCore.QPointF) -> Optional[Tuple[int, int]]:
        """Return the ``(col, row)`` split cell under widget point ``pos``."""
        dims = self._split_grid_dims()
        if dims is None or self._draw_rect.isEmpty():
            return None
        iw, ih, sw, sh = dims
        scale = self._draw_rect.width() / iw if iw else 0
        if scale <= 0:
            return None
        x = (pos.x() - self._draw_rect.left()) / scale
        y = (pos.y() - self._draw_rect.top()) / scale
        if x < 0 or y < 0 or x >= iw or y >= ih:
            return None
        return (int(x // sw), int(y // sh))

    def cell_box_at(self, pos: QtCore.QPointF) -> Optional[Tuple[int, int, int, int]]:
        """Return the cell box ``(left, top, right, bottom)`` under widget ``pos``.

        Public helper for the right-click menu: maps a widget point to the split
        cell it lands on and returns that cell's displayed-image pixel box, or
        ``None`` when split mode is off or the point is outside the image.
        """
        if not self._split_mode:
            return None
        self._draw_rect = self._compute_draw_rect()
        cell = self._cell_at(pos)
        if cell is None:
            return None
        return self._cell_box(*cell)

    def _cell_box(self, col: int, row: int) -> Optional[Tuple[int, int, int, int]]:
        """Return the ``(left, top, right, bottom)`` image-pixel box of a cell."""
        dims = self._split_grid_dims()
        if dims is None:
            return None
        iw, ih, sw, sh = dims
        left = col * sw
        top = row * sh
        right = min(left + sw, iw)
        bottom = min(top + sh, ih)
        if right <= left or bottom <= top:
            return None
        return (left, top, right, bottom)

    def _paint_split_grid(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        """Draw the split cell grid and highlight the hovered cell."""
        dims = self._split_grid_dims()
        if dims is None:
            return
        iw, ih, sw, sh = dims
        scale = rect.width() / iw if iw else 0
        if scale <= 0:
            return
        painter.save()
        painter.setClipRect(rect)
        # Highlight the hovered cell first (under the grid lines).
        if self._split_hover is not None:
            box = self._cell_box(*self._split_hover)
            if box is not None:
                l, t, r, b = box
                hr = QtCore.QRectF(
                    rect.left() + l * scale, rect.top() + t * scale,
                    (r - l) * scale, (b - t) * scale,
                )
                painter.fillRect(hr, QtGui.QColor(255, 215, 0, 70))
        pen = QtGui.QPen(QtGui.QColor(255, 215, 0, 170), 1)
        painter.setPen(pen)
        x = 0
        while x <= iw:
            sx = rect.left() + x * scale
            painter.drawLine(
                QtCore.QPointF(sx, rect.top()),
                QtCore.QPointF(sx, rect.top() + ih * scale),
            )
            x += sw
        y = 0
        while y <= ih:
            sy = rect.top() + y * scale
            painter.drawLine(
                QtCore.QPointF(rect.left(), sy),
                QtCore.QPointF(rect.left() + iw * scale, sy),
            )
            y += sh
        # A bold border around the hovered cell so the click target is obvious.
        if self._split_hover is not None:
            box = self._cell_box(*self._split_hover)
            if box is not None:
                l, t, r, b = box
                hr = QtCore.QRectF(
                    rect.left() + l * scale, rect.top() + t * scale,
                    (r - l) * scale, (b - t) * scale,
                )
                painter.setPen(QtGui.QPen(QtGui.QColor(255, 235, 120), 2))
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawRect(hr)
        painter.restore()

    def _paint_diamond_overlay(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        """Draw a centered, tile-ratio diamond selection outline within ``rect``."""
        rw = max(1, self._cell_width)
        rh = max(1, self._cell_height)
        diamond_w = min(rect.width(), rect.height() * rw / rh)
        diamond_h = diamond_w * rh / rw
        cx = rect.center().x()
        cy = rect.center().y()
        poly = QtGui.QPolygonF(
            [
                QtCore.QPointF(cx, cy - diamond_h / 2.0),
                QtCore.QPointF(cx + diamond_w / 2.0, cy),
                QtCore.QPointF(cx, cy + diamond_h / 2.0),
                QtCore.QPointF(cx - diamond_w / 2.0, cy),
            ]
        )
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 215, 0), 2, QtCore.Qt.PenStyle.DashLine))
        painter.drawPolygon(poly)
        painter.restore()

    # -- Internal drag bookkeeping --------------------------------------
    def _cancel_drags(self) -> None:
        """Reset every drag state (crop / resize / edge-crop) and hide the rubber-band."""
        self._drag_origin = None
        self._resize_corner = None
        self._resize_factor = 1.0
        self._crop_edge = None
        self._crop_rect = QtCore.QRectF()
        self._rubber.hide()

    # -- Geometry helpers ----------------------------------------------
    def _compute_draw_rect(self) -> QtCore.QRectF:
        """Return the fit-to-widget rectangle for the current image.

        The image is scaled to fit inside the widget while preserving its
        aspect ratio, then centered. Returns an empty rect when there is no
        image.
        """
        if self._pixmap is None or self._pixmap.isNull():
            return QtCore.QRectF()
        iw = self._pixmap.width()
        ih = self._pixmap.height()
        if iw <= 0 or ih <= 0:
            return QtCore.QRectF()
        ww = max(1, self.width())
        wh = max(1, self.height())
        scale = min(ww / iw, wh / ih)
        dw = iw * scale
        dh = ih * scale
        dx = (ww - dw) / 2.0
        dy = (wh - dh) / 2.0
        return QtCore.QRectF(dx, dy, dw, dh)

    def _corner_points(self, rect: QtCore.QRectF) -> List[QtCore.QPointF]:
        """Return the four corners of ``rect`` ordered ``[TL, TR, BL, BR]``."""
        return [
            rect.topLeft(),
            rect.topRight(),
            rect.bottomLeft(),
            rect.bottomRight(),
        ]

    def _handle_rects(self) -> List[QtCore.QRectF]:
        """Return the four square handle rectangles in widget coordinates.

        Empty list when there is no image to attach handles to.
        """
        if self._draw_rect.isEmpty():
            return []
        h = self._HANDLE
        rects: List[QtCore.QRectF] = []
        for pt in self._corner_points(self._draw_rect):
            rects.append(QtCore.QRectF(pt.x() - h / 2.0, pt.y() - h / 2.0, h, h))
        return rects

    def _hit_handle(self, pos: QtCore.QPointF) -> Optional[int]:
        """Return the corner index whose handle contains ``pos``, else ``None``.

        Handles are padded by :attr:`_HANDLE_SLACK` to make them easy to grab.
        """
        slack = self._HANDLE_SLACK
        for idx, rect in enumerate(self._handle_rects()):
            if rect.adjusted(-slack, -slack, slack, slack).contains(pos):
                return idx
        return None

    def _opposite_corner(self, corner: int) -> int:
        """Return the corner index diagonally opposite ``corner``."""
        return {self._TL: self._BR, self._TR: self._BL,
                self._BL: self._TR, self._BR: self._TL}[corner]

    def _handle_cursor(self, corner: int) -> QtGui.QCursor:
        """Return the diagonal resize cursor matching ``corner``.

        Top-left / bottom-right share the ``\\`` diagonal (FDiag); top-right /
        bottom-left share the ``/`` diagonal (BDiag).
        """
        if corner in (self._TL, self._BR):
            shape = QtCore.Qt.CursorShape.SizeFDiagCursor
        else:
            shape = QtCore.Qt.CursorShape.SizeBDiagCursor
        return QtGui.QCursor(shape)

    # -- Edge (side) crop handles --------------------------------------
    def _edge_hit_rects(self) -> dict:
        """Return widget-space hit bands for the four side crop handles.

        Each band runs along a side of the image, inset from the corners (by the
        corner-handle size) so it never overlaps a corner resize handle. Returns
        an empty dict when there is no image or it is too small for side handles.
        """
        if self._draw_rect.isEmpty() or not self._crop_enabled:
            return {}
        d = self._draw_rect
        g = self._HANDLE                  # keep clear of the corner handles
        s = self._EDGE_SLACK
        if d.width() <= 2 * g or d.height() <= 2 * g:
            return {}
        return {
            self._LEFT: QtCore.QRectF(d.left() - s, d.top() + g, 2 * s, d.height() - 2 * g),
            self._RIGHT: QtCore.QRectF(d.right() - s, d.top() + g, 2 * s, d.height() - 2 * g),
            self._TOP: QtCore.QRectF(d.left() + g, d.top() - s, d.width() - 2 * g, 2 * s),
            self._BOTTOM: QtCore.QRectF(d.left() + g, d.bottom() - s, d.width() - 2 * g, 2 * s),
        }

    def _edge_bar_rects(self) -> dict:
        """Return the small visible handle bars centered on each side."""
        if self._draw_rect.isEmpty() or not self._crop_enabled:
            return {}
        d = self._draw_rect
        length = self._EDGE_BAR_LEN
        thick = self._EDGE_BAR_THICK
        cx = d.center().x()
        cy = d.center().y()
        return {
            self._LEFT: QtCore.QRectF(d.left() - thick / 2.0, cy - length / 2.0, thick, length),
            self._RIGHT: QtCore.QRectF(d.right() - thick / 2.0, cy - length / 2.0, thick, length),
            self._TOP: QtCore.QRectF(cx - length / 2.0, d.top() - thick / 2.0, length, thick),
            self._BOTTOM: QtCore.QRectF(cx - length / 2.0, d.bottom() - thick / 2.0, length, thick),
        }

    def _hit_edge(self, pos: QtCore.QPointF) -> Optional[str]:
        """Return the side whose crop band contains ``pos``, else ``None``."""
        for edge, rect in self._edge_hit_rects().items():
            if rect.contains(pos):
                return edge
        return None

    def _edge_cursor(self, edge: str) -> QtGui.QCursor:
        """Return a horizontal / vertical resize cursor matching ``edge``."""
        if edge in (self._LEFT, self._RIGHT):
            shape = QtCore.Qt.CursorShape.SizeHorCursor
        else:
            shape = QtCore.Qt.CursorShape.SizeVerCursor
        return QtGui.QCursor(shape)

    def _crop_rect_for(self, edge: str, pos: QtCore.QPointF) -> QtCore.QRectF:
        """Return the kept-region rect (widget coords) for dragging ``edge`` to ``pos``.

        Only the dragged side moves inward; the other three sides stay on the
        image bounds, so dragging an edge trims that side. The moving edge is
        clamped to the image and kept at least :attr:`_EDGE_MIN_GAP` from the
        opposite side.
        """
        d = self._draw_rect
        gap = self._EDGE_MIN_GAP
        left, top, right, bottom = d.left(), d.top(), d.right(), d.bottom()
        if edge == self._LEFT:
            left = min(max(pos.x(), d.left()), d.right() - gap)
        elif edge == self._RIGHT:
            right = min(max(pos.x(), d.left() + gap), d.right())
        elif edge == self._TOP:
            top = min(max(pos.y(), d.top()), d.bottom() - gap)
        elif edge == self._BOTTOM:
            bottom = min(max(pos.y(), d.top() + gap), d.bottom())
        return QtCore.QRectF(
            QtCore.QPointF(left, top), QtCore.QPointF(right, bottom)
        ).normalized()

    def _display_to_image(self, box: QtCore.QRect) -> Optional[Tuple[int, int, int, int]]:
        """Map a widget-space rectangle to displayed-image pixel coordinates.

        Inverts the fit scale/offset computed in :meth:`_compute_draw_rect`,
        clamps the result to the image bounds, and orders the edges. Returns
        ``None`` when there is no image or the mapped box has zero area.

        Args:
            box: Selection rectangle in widget (logical) coordinates.

        Returns:
            ``(left, top, right, bottom)`` integer pixel box, or ``None``.
        """
        if self._pixmap is None or self._pixmap.isNull():
            return None
        draw = self._draw_rect
        if draw.isEmpty() or draw.width() <= 0 or draw.height() <= 0:
            return None
        iw = self._pixmap.width()
        ih = self._pixmap.height()
        scale = draw.width() / iw  # uniform scale (width == height ratio)
        if scale <= 0:
            return None

        # Translate widget coords -> image pixel coords.
        x1 = (box.left() - draw.left()) / scale
        y1 = (box.top() - draw.top()) / scale
        x2 = (box.right() - draw.left()) / scale
        y2 = (box.bottom() - draw.top()) / scale

        left = int(round(min(x1, x2)))
        top = int(round(min(y1, y2)))
        right = int(round(max(x1, x2)))
        bottom = int(round(max(y1, y2)))

        # Clamp to image bounds.
        left = max(0, min(left, iw))
        right = max(0, min(right, iw))
        top = max(0, min(top, ih))
        bottom = max(0, min(bottom, ih))

        if right <= left or bottom <= top:
            return None
        return (left, top, right, bottom)

    def _factor_for(self, pos: QtCore.QPointF) -> float:
        """Compute the aspect-preserving resize factor for the current drag.

        The factor is the ratio of the dragged corner's distance from the fixed
        anchor *now* versus *at drag start*, measured by projecting the live
        mouse vector onto the original corner->anchor diagonal. This keeps the
        aspect ratio while honoring the dominant drag direction. The result is
        clamped to at least :attr:`_MIN_FACTOR`.
        """
        anchor = self._resize_anchor
        v0 = self._resize_start - anchor          # original diagonal vector
        len0_sq = v0.x() * v0.x() + v0.y() * v0.y()
        if len0_sq <= 0:
            return 1.0
        v1 = pos - anchor                          # live diagonal vector
        # Project v1 onto v0 to keep the motion along the original diagonal.
        proj = (v1.x() * v0.x() + v1.y() * v0.y()) / len0_sq
        return max(self._MIN_FACTOR, proj)

    def _preview_rect(self) -> QtCore.QRectF:
        """Return the dashed-preview rectangle for the live resize drag."""
        anchor = self._resize_anchor
        v0 = self._resize_start - anchor
        new_corner = QtCore.QPointF(
            anchor.x() + v0.x() * self._resize_factor,
            anchor.y() + v0.y() * self._resize_factor,
        )
        return QtCore.QRectF(anchor, new_corner).normalized()

    # -- Painting -------------------------------------------------------
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Paint the background, the fit-to-widget image, handles, and hints."""
        painter = QtGui.QPainter(self)
        try:
            # Solid backdrop.
            painter.fillRect(self.rect(), QtGui.QColor(54, 54, 58))

            self._draw_rect = self._compute_draw_rect()
            if self._draw_rect.isEmpty():
                self._paint_placeholder(painter)
                return

            target = self._draw_rect
            # Checkerboard behind the image so transparency is visible.
            self._paint_checker(painter, target)
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawPixmap(target, self._pixmap, QtCore.QRectF(self._pixmap.rect()))

            # Thin border around the image area.
            painter.setPen(QtGui.QPen(QtGui.QColor(120, 120, 124)))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(target.adjusted(0, 0, -1, -1))

            if self._split_mode:
                # Grid Split takes over the canvas: only the cell grid is shown
                # (no crop / resize / diamond gestures while splitting).
                self._paint_split_grid(painter, target)
                self._paint_hint(painter)
                return

            if self._diamond_overlay:
                self._paint_diamond_overlay(painter, target)

            self._paint_handles(painter)
            self._paint_edge_handles(painter)
            if self._resize_corner is not None:
                self._paint_resize_preview(painter)
            elif self._crop_edge is not None:
                self._paint_crop_preview(painter)
            self._paint_hint(painter)
        finally:
            painter.end()

    def _paint_placeholder(self, painter: QtGui.QPainter) -> None:
        """Draw a centered hint when no image is loaded."""
        painter.setPen(QtGui.QPen(QtGui.QColor(150, 150, 154)))
        painter.drawText(
            self.rect(),
            QtCore.Qt.AlignmentFlag.AlignCenter,
            "No tile selected",
        )

    def _paint_checker(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        """Fill ``rect`` with a light/dark checkerboard."""
        painter.save()
        painter.setClipRect(rect)
        light = QtGui.QColor(200, 200, 204)
        dark = QtGui.QColor(160, 160, 164)
        painter.fillRect(rect, light)
        step = self._CHECKER
        x0 = int(rect.left())
        y0 = int(rect.top())
        x1 = int(rect.right()) + step
        y1 = int(rect.bottom()) + step
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(dark)
        row = 0
        y = y0
        while y < y1:
            col = 0
            x = x0
            while x < x1:
                if (row + col) % 2 == 1:
                    painter.drawRect(x, y, step, step)
                col += 1
                x += step
            row += 1
            y += step
        painter.restore()

    def _paint_handles(self, painter: QtGui.QPainter) -> None:
        """Draw the four corner resize handles as small outlined squares."""
        rects = self._handle_rects()
        if not rects:
            return
        painter.save()
        fill = QtGui.QColor(255, 255, 255)
        border = QtGui.QColor(40, 120, 220)
        active_fill = QtGui.QColor(255, 230, 120)
        painter.setBrush(QtGui.QBrush(fill))
        for idx, rect in enumerate(rects):
            if idx == self._resize_corner:
                painter.setBrush(QtGui.QBrush(active_fill))
            else:
                painter.setBrush(QtGui.QBrush(fill))
            painter.setPen(QtGui.QPen(border, 1.5))
            painter.drawRect(rect)
        painter.restore()

    def _paint_resize_preview(self, painter: QtGui.QPainter) -> None:
        """Draw the in-progress resize: dashed rect + a bold W×H pixel readout."""
        preview = self._preview_rect()
        if preview.isEmpty() or self._pixmap is None:
            return
        painter.save()
        pen = QtGui.QPen(QtGui.QColor(255, 230, 120), 2)
        pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRect(preview)

        # New pixel size = current display size * the live drag factor.
        new_w = max(1, round(self._pixmap.width() * self._resize_factor))
        new_h = max(1, round(self._pixmap.height() * self._resize_factor))
        text = f"{new_w} × {new_h} px"

        font = painter.font()
        font.setPointSize(max(16, font.pointSize() + 6))
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        box_w = metrics.horizontalAdvance(text) + 20
        box_h = metrics.height() + 12
        center = preview.center()
        box = QtCore.QRectF(
            center.x() - box_w / 2.0, center.y() - box_h / 2.0, box_w, box_h
        )
        # Dark rounded plate behind a bright readout so it is easy to read.
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0, 190))
        painter.drawRoundedRect(box, 6, 6)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255)))
        painter.drawText(box, QtCore.Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def _paint_edge_handles(self, painter: QtGui.QPainter) -> None:
        """Draw the four side crop handles as small bars centered on each edge."""
        bars = self._edge_bar_rects()
        if not bars:
            return
        painter.save()
        # Teal marks these as CROP handles, distinct from the blue resize corners.
        border = QtGui.QColor(0, 170, 140)
        fill = QtGui.QColor(225, 255, 248)
        active = QtGui.QColor(120, 255, 215)
        for edge, bar in bars.items():
            painter.setBrush(QtGui.QBrush(active if edge == self._crop_edge else fill))
            painter.setPen(QtGui.QPen(border, 1.5))
            painter.drawRoundedRect(bar, 2, 2)
        painter.restore()

    def _paint_crop_preview(self, painter: QtGui.QPainter) -> None:
        """Dim the side being cropped away, outline what remains, show its size."""
        if self._crop_rect.isEmpty() or self._pixmap is None:
            return
        painter.save()
        # Dim the cropped-away region (the whole image minus the kept rect).
        painter.setClipRect(self._draw_rect)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0, 120))
        whole = QtGui.QPainterPath()
        whole.addRect(self._draw_rect)
        kept = QtGui.QPainterPath()
        kept.addRect(self._crop_rect)
        painter.drawPath(whole.subtracted(kept))
        painter.setClipping(False)

        # Dashed outline of the kept region.
        pen = QtGui.QPen(QtGui.QColor(255, 230, 120), 2)
        pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRect(self._crop_rect)

        # Readout: the resulting (kept) pixel size.
        box = self._display_to_image(self._crop_rect.toRect())
        if box is not None:
            w = box[2] - box[0]
            h = box[3] - box[1]
            text = f"Crop  {w} × {h} px"
            font = painter.font()
            font.setPointSize(max(14, font.pointSize() + 4))
            font.setBold(True)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            bw = metrics.horizontalAdvance(text) + 18
            bh = metrics.height() + 10
            c = self._crop_rect.center()
            plate = QtCore.QRectF(c.x() - bw / 2.0, c.y() - bh / 2.0, bw, bh)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(0, 0, 0, 190))
            painter.drawRoundedRect(plate, 6, 6)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255)))
            painter.drawText(plate, QtCore.Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def _paint_hint(self, painter: QtGui.QPainter) -> None:
        """Draw a faint usage hint along the bottom edge of the widget."""
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor(170, 170, 176)))
        hint_rect = QtCore.QRectF(0, self.height() - 20, self.width(), 18)
        if self._split_mode:
            text = "Grid Split: click a cell to copy it • paste it into the Tileset Preview"
        else:
            text = (
                "Drag a corner to resize • Drag an edge to crop that side • "
                "Drag inside to crop • S: mask to diamond"
            )
        painter.drawText(
            hint_rect,
            QtCore.Qt.AlignmentFlag.AlignCenter,
            text,
        )
        painter.restore()

    # -- Keyboard interaction ------------------------------------------
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        """Shortcuts: ``S`` diamond select, ``Cmd/Ctrl+C`` copy, ``Cmd/Ctrl+P`` paste to tileset."""
        mods = event.modifiers()
        key = event.key()
        no_mod = QtCore.Qt.KeyboardModifier.NoModifier
        ctrl = QtCore.Qt.KeyboardModifier.ControlModifier  # Cmd on macOS
        if mods == no_mod and key == QtCore.Qt.Key.Key_S and self._pixmap is not None:
            self.diamond_requested.emit()
            event.accept()
            return
        if mods == ctrl and key == QtCore.Qt.Key.Key_C:
            self.copy_requested.emit()
            event.accept()
            return
        if mods == ctrl and key == QtCore.Qt.Key.Key_V:
            self.paste_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    # -- Mouse interaction ---------------------------------------------
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Start a resize drag on a handle, or a crop rubber-band inside."""
        if event.button() != QtCore.Qt.MouseButton.LeftButton or self._pixmap is None:
            super().mousePressEvent(event)
            return
        pos = event.position()
        # Geometry is recomputed every paint; ensure it is current before use.
        self._draw_rect = self._compute_draw_rect()

        if self._split_mode:
            # Grid Split: a click on a cell copies that cell out.
            cell = self._cell_at(pos)
            if cell is not None:
                box = self._cell_box(*cell)
                if box is not None:
                    self._split_hover = cell
                    self.update()
                    self.cell_picked.emit(box)
            event.accept()
            return

        corner = self._hit_handle(pos)
        if corner is not None:
            # Begin a resize drag anchored at the opposite corner.
            corners = self._corner_points(self._draw_rect)
            self._resize_corner = corner
            self._resize_anchor = corners[self._opposite_corner(corner)]
            self._resize_start = corners[corner]
            self._resize_factor = 1.0
            self.setCursor(self._handle_cursor(corner))
            self.update()
            event.accept()
            return

        edge = self._hit_edge(pos)
        if edge is not None:
            # Begin an edge-crop drag: trim the dragged side inward.
            self._crop_edge = edge
            self._crop_rect = self._crop_rect_for(edge, pos)
            self.setCursor(self._edge_cursor(edge))
            self.update()
            event.accept()
            return

        # Otherwise, begin a crop rubber-band selection (when crop is allowed).
        if not self._crop_enabled:
            super().mousePressEvent(event)
            return
        self._drag_origin = pos.toPoint()
        self._rubber.setGeometry(QtCore.QRect(self._drag_origin, QtCore.QSize()))
        self._rubber.show()
        event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """Update the active drag, or swap the cursor when hovering a handle."""
        pos = event.position()

        if self._split_mode:
            # Update the hovered cell highlight as the cursor moves.
            self._draw_rect = self._compute_draw_rect()
            cell = self._cell_at(pos)
            if cell != self._split_hover:
                self._split_hover = cell
                self.update()
            self.setCursor(
                QtCore.Qt.CursorShape.PointingHandCursor
                if cell is not None
                else QtCore.Qt.CursorShape.ArrowCursor
            )
            event.accept()
            return

        if self._resize_corner is not None:
            # Live resize: recompute the factor and repaint the preview.
            self._resize_factor = self._factor_for(pos)
            self.update()
            event.accept()
            return

        if self._crop_edge is not None:
            # Live edge-crop: move the dragged side and repaint the preview.
            self._crop_rect = self._crop_rect_for(self._crop_edge, pos)
            self.update()
            event.accept()
            return

        if self._drag_origin is not None:
            current = pos.toPoint()
            self._rubber.setGeometry(
                QtCore.QRect(self._drag_origin, current).normalized()
            )
            event.accept()
            return

        # Idle hover: indicate the gesture available under the cursor.
        if self._pixmap is not None:
            self._draw_rect = self._compute_draw_rect()
            corner = self._hit_handle(pos)
            if corner is not None:
                self.setCursor(self._handle_cursor(corner))
            else:
                edge = self._hit_edge(pos)
                if edge is not None:
                    self.setCursor(self._edge_cursor(edge))
                else:
                    self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        """Finish the active drag and emit the matching signal."""
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return

        if self._split_mode:
            # The cell was already copied on press; nothing to finish here.
            event.accept()
            return

        if self._resize_corner is not None:
            factor = self._factor_for(event.position())
            self._resize_corner = None
            self._resize_factor = 1.0
            self.unsetCursor()
            self.update()
            # Suppress near-identity resizes to avoid spurious edits.
            if abs(factor - 1.0) >= self._NOOP_EPS:
                self.resize_requested.emit(float(factor))
            event.accept()
            return

        if self._crop_edge is not None:
            rect = self._crop_rect_for(self._crop_edge, event.position())
            self._crop_edge = None
            self._crop_rect = QtCore.QRectF()
            self.unsetCursor()
            self.update()
            box = self._display_to_image(rect.toRect())
            if box is not None:
                self.crop_selected.emit(box)
            event.accept()
            return

        if self._drag_origin is not None:
            origin = self._drag_origin
            self._drag_origin = None
            end = event.position().toPoint()
            self._rubber.hide()
            selection = QtCore.QRect(origin, end).normalized()
            box = self._display_to_image(selection)
            if box is not None:
                self.crop_selected.emit(box)
            event.accept()
            return

        super().mouseReleaseEvent(event)
