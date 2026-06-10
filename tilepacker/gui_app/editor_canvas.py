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
        self.update()

    def clear(self) -> None:
        """Clear the displayed image and cancel any active drag."""
        self._pixmap = None
        self._cancel_drags()
        self.unsetCursor()
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
        """Reset both the crop and resize drag states and hide the rubber-band."""
        self._drag_origin = None
        self._resize_corner = None
        self._resize_factor = 1.0
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

            if self._diamond_overlay:
                self._paint_diamond_overlay(painter, target)

            self._paint_handles(painter)
            if self._resize_corner is not None:
                self._paint_resize_preview(painter)
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

    def _paint_hint(self, painter: QtGui.QPainter) -> None:
        """Draw a faint usage hint along the bottom edge of the widget."""
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor(170, 170, 176)))
        hint_rect = QtCore.QRectF(0, self.height() - 20, self.width(), 18)
        painter.drawText(
            hint_rect,
            QtCore.Qt.AlignmentFlag.AlignCenter,
            "Drag a corner to resize • Drag inside to crop • S: mask to diamond",
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

        # Otherwise, begin a crop rubber-band selection.
        self._drag_origin = pos.toPoint()
        self._rubber.setGeometry(QtCore.QRect(self._drag_origin, QtCore.QSize()))
        self._rubber.show()
        event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """Update the active drag, or swap the cursor when hovering a handle."""
        pos = event.position()

        if self._resize_corner is not None:
            # Live resize: recompute the factor and repaint the preview.
            self._resize_factor = self._factor_for(pos)
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

        # Idle hover: indicate resizability over a handle.
        if self._pixmap is not None:
            self._draw_rect = self._compute_draw_rect()
            corner = self._hit_handle(pos)
            if corner is not None:
                self.setCursor(self._handle_cursor(corner))
            else:
                self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        """Finish the active drag and emit the matching signal."""
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
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
