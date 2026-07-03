"""Left panel: the isometric tile editor for the minimal (gui2) app.

The panel has, top to bottom:

* A command row: Add image, Remove image, the Split Grid size (width x height)
  with an Apply button, and Copy.
* The image list (one row per imported source image).
* The editor canvas: it shows the selected source image with an isometric
  diamond grid overlaid, and lets you drag to select a diamond-shaped area of
  cells. Copy cuts those cells (diamond-masked) onto the clipboard.

The canvas is intentionally simple: fit-to-widget view, an isometric grid, a
drag marquee that selects whole diamond cells, and nothing else.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets

from tilepacker.gui2 import isogrid
from tilepacker.gui2.qtutil import pil_to_qpixmap, qimage_to_pil
from tilepacker.gui2.state import MIME_CELLS, AppState

#: Image file extensions accepted by drag-and-drop onto the editor.
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")

__all__ = ["EditorPanel", "EditorCanvas"]


class EditorCanvas(QtWidgets.QWidget):
    """Shows one source image with an isometric grid and a drag area-select.

    Drag anywhere over the image to select the diamond cluster the drag spans
    (isometric-tile rectangle). The selection is reported by
    :meth:`selected_cells` as a list of diamond lattice indices ``(a, b)``.
    """

    #: Emitted whenever the selected-cell set changes (carries the count).
    selection_changed = QtCore.Signal(int)
    #: Emitted just before an export drag starts, so the panel can copy the
    #: current selection to the clipboard (the drop then pastes it).
    prepare_drag = QtCore.Signal()
    #: Emitted when image files are dropped onto the editor: a list of paths.
    files_dropped = QtCore.Signal(list)
    #: Emitted when an image (not a file) is dropped: a PIL image.
    image_dropped = QtCore.Signal(object)

    #: Pointer travel (px) before a press on the selection becomes a drag-out.
    DRAG_THRESHOLD = 6

    BACKGROUND = QtGui.QColor("#2b2b2b")
    GRID_COLOR = QtGui.QColor(255, 215, 0, 140)
    SELECT_FILL = QtGui.QColor(0, 200, 180, 95)
    SELECT_LINE = QtGui.QColor(0, 235, 205)
    MARQUEE_LINE = QtGui.QColor(0, 235, 205)
    MARQUEE_FILL = QtGui.QColor(0, 200, 180, 40)
    PADDING = 10

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._pixmap: Optional[QtGui.QPixmap] = None
        self._img_w = 0
        self._img_h = 0
        self._cell_w = 64
        self._cell_h = 32
        self._show_grid = False
        # Selection shape: "diamond" (isometric-tile rectangle) or "rect"
        # (screen-aligned rectangle over the diamond cells).
        self._select_shape = "diamond"
        self._draw_rect = QtCore.QRectF()
        self._selected: set = set()
        self._selecting = False
        self._press: Optional[QtCore.QPointF] = None
        self._cur: Optional[QtCore.QPointF] = None
        # Selection committed before the current drag (kept when Shift-adding),
        # and the drag mode: "replace" (plain) or "add" (Shift accumulates).
        self._base_selected: set = set()
        self._mode = "replace"
        # Drag-out (export to preview) state: a press on an already-selected
        # cell arms a drag; moving past the threshold starts a QDrag.
        self._drag_candidate = False
        self._drag_origin: Optional[QtCore.QPointF] = None
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

    # -- Public API -----------------------------------------------------
    def set_image(self, image: Optional[Image.Image]) -> None:
        """Show ``image`` (or clear the canvas when ``None``); resets selection."""
        if image is None:
            self._pixmap = None
            self._img_w = self._img_h = 0
        else:
            self._pixmap = pil_to_qpixmap(image)
            self._img_w, self._img_h = image.size
        self._clear_selection()
        self.update()

    def set_grid(self, cell_w: int, cell_h: int, show: bool) -> None:
        """Set the isometric cell size and whether the grid is shown."""
        self._cell_w = max(2, int(cell_w))
        self._cell_h = max(2, int(cell_h))
        self._show_grid = bool(show)
        self._clear_selection()
        self.update()

    def set_select_shape(self, shape: str) -> None:
        """Set the drag-select shape: ``"diamond"`` or ``"rect"``."""
        shape = shape if shape in ("diamond", "rect") else "diamond"
        if shape != self._select_shape:
            self._select_shape = shape
            self._clear_selection()
            self.update()

    def selected_cells(self) -> List[Tuple[int, int]]:
        """Return the selected diamond indices in natural reading order."""
        return sorted(self._selected, key=lambda c: isogrid.iso_reading_key(*c))

    def clear_selection(self) -> None:
        """Public: drop the current selection and repaint."""
        self._clear_selection()
        self.update()

    # -- Geometry -------------------------------------------------------
    def _compute_draw_rect(self) -> QtCore.QRectF:
        """Return the fit-to-widget rectangle the image is drawn into."""
        if self._pixmap is None or self._img_w <= 0 or self._img_h <= 0:
            return QtCore.QRectF()
        pad = self.PADDING
        aw = max(1, self.width() - 2 * pad)
        ah = max(1, self.height() - 2 * pad)
        scale = min(aw / self._img_w, ah / self._img_h)
        w = self._img_w * scale
        h = self._img_h * scale
        x = pad + (aw - w) / 2.0
        y = pad + (ah - h) / 2.0
        return QtCore.QRectF(x, y, w, h)

    def _scale(self) -> float:
        return self._draw_rect.width() / self._img_w if self._img_w else 0.0

    def _to_image(self, pos: QtCore.QPointF) -> Tuple[float, float]:
        s = self._scale()
        if s <= 0:
            return (0.0, 0.0)
        return ((pos.x() - self._draw_rect.left()) / s, (pos.y() - self._draw_rect.top()) / s)

    def _diamond_poly(self, a: int, b: int) -> QtGui.QPolygonF:
        """Return the widget-space diamond polygon for cell ``(a, b)``."""
        s = self._scale()
        hw = self._cell_w / 2.0
        hh = self._cell_h / 2.0
        cx = self._draw_rect.left() + a * hw * s
        cy = self._draw_rect.top() + b * hh * s
        ehw = hw * s
        ehh = hh * s
        return QtGui.QPolygonF(
            [
                QtCore.QPointF(cx, cy - ehh),
                QtCore.QPointF(cx + ehw, cy),
                QtCore.QPointF(cx, cy + ehh),
                QtCore.QPointF(cx - ehw, cy),
            ]
        )

    # -- Painting -------------------------------------------------------
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        try:
            painter.fillRect(self.rect(), self.BACKGROUND)
            self._draw_rect = self._compute_draw_rect()
            if self._pixmap is None:
                painter.setPen(QtGui.QColor("#aaaaaa"))
                painter.drawText(
                    self.rect(),
                    int(QtCore.Qt.AlignmentFlag.AlignCenter),
                    "Add an image (or drop an image / paste one here), then Split Grid",
                )
                return
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawPixmap(self._draw_rect, self._pixmap, QtCore.QRectF(self._pixmap.rect()))
            if self._show_grid:
                self._paint_grid(painter)
                self._paint_selection(painter)
                self._paint_marquee(painter)
        finally:
            painter.end()

    def _paint_grid(self, painter: QtGui.QPainter) -> None:
        painter.setPen(QtGui.QPen(self.GRID_COLOR, 1))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        hw = self._cell_w / 2.0
        hh = self._cell_h / 2.0
        a_max = int(self._img_w / hw) + 2 if hw else 0
        b_max = int(self._img_h / hh) + 2 if hh else 0
        for a in range(0, a_max + 1):
            for b in range(0, b_max + 1):
                if (a + b) % 2 != 0:
                    continue
                if isogrid.cell_box(a, b, self._cell_w, self._cell_h, self._img_w, self._img_h):
                    painter.drawPolygon(self._diamond_poly(a, b))

    def _paint_selection(self, painter: QtGui.QPainter) -> None:
        if not self._selected:
            return
        painter.setPen(QtGui.QPen(self.SELECT_LINE, 2))
        painter.setBrush(self.SELECT_FILL)
        for a, b in self._selected:
            painter.drawPolygon(self._diamond_poly(a, b))

    def _paint_marquee(self, painter: QtGui.QPainter) -> None:
        if not self._selecting or self._press is None or self._cur is None:
            return
        pen = QtGui.QPen(self.MARQUEE_LINE, 1.5)
        pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(self.MARQUEE_FILL)
        if self._select_shape == "rect":
            rect = QtCore.QRectF(self._press, self._cur).normalized()
            if not self._draw_rect.isEmpty():
                rect = rect.intersected(self._draw_rect)
            if not rect.isEmpty():
                painter.drawRect(rect)
            return
        poly = self._marquee_poly()
        if poly is not None:
            painter.drawPolygon(poly)

    def _marquee_poly(self) -> Optional[QtGui.QPolygonF]:
        """Return the diamond bounding the current drag (isometric-tile rect)."""
        s = self._scale()
        if s <= 0:
            return None
        x0, y0 = self._to_image(self._press)
        x1, y1 = self._to_image(self._cur)
        a0, b0 = isogrid.cell_at(x0, y0, self._cell_w, self._cell_h)
        a1, b1 = isogrid.cell_at(x1, y1, self._cell_w, self._cell_h)
        i0, j0 = (a0 + b0) // 2, (a0 - b0) // 2
        i1, j1 = (a1 + b1) // 2, (a1 - b1) // 2
        ilo, ihi = min(i0, i1), max(i0, i1)
        jlo, jhi = min(j0, j1), max(j0, j1)
        hw = self._cell_w / 2.0
        hh = self._cell_h / 2.0
        ehw = hw * s
        ehh = hh * s

        def center(i: int, j: int) -> Tuple[float, float]:
            cx = self._draw_rect.left() + (i + j) * hw * s
            cy = self._draw_rect.top() + (i - j) * hh * s
            return cx, cy

        nx, ny = center(ilo, jhi)   # top
        ex, ey = center(ihi, jhi)   # right
        sx, sy = center(ihi, jlo)   # bottom
        wx, wy = center(ilo, jlo)   # left
        return QtGui.QPolygonF(
            [
                QtCore.QPointF(nx, ny - ehh),
                QtCore.QPointF(ex + ehw, ey),
                QtCore.QPointF(sx, sy + ehh),
                QtCore.QPointF(wx - ehw, wy),
            ]
        )

    # -- Drag & drop (add source images) --------------------------------
    def _drop_has_content(self, mime) -> bool:
        if mime.hasImage():
            return True
        if mime.hasUrls():
            return any(
                u.isLocalFile() and u.toLocalFile().lower().endswith(_IMAGE_EXTS)
                for u in mime.urls()
            )
        return False

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # noqa: N802
        if self._drop_has_content(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:  # noqa: N802
        if self._drop_has_content(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        # Prefer real files (they have a path -> restored on workspace reload).
        if mime.hasUrls():
            paths = [
                u.toLocalFile()
                for u in mime.urls()
                if u.isLocalFile() and u.toLocalFile().lower().endswith(_IMAGE_EXTS)
            ]
            if paths:
                self.files_dropped.emit(paths)
                event.acceptProposedAction()
                return
        if mime.hasImage():
            qimg = mime.imageData()
            if isinstance(qimg, QtGui.QImage) and not qimg.isNull():
                self.image_dropped.emit(qimage_to_pil(qimg))
                event.acceptProposedAction()
                return

    # -- Mouse ----------------------------------------------------------
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if (
            event.button() != QtCore.Qt.MouseButton.LeftButton
            or self._pixmap is None
            or not self._show_grid
        ):
            super().mousePressEvent(event)
            return
        self._draw_rect = self._compute_draw_rect()
        pos = event.position()
        shift = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
        # Pressing (no Shift) on an already-selected cell arms a drag-out: the
        # selection can be dragged and dropped onto the preview.
        if not shift and self._selected:
            x, y = self._to_image(pos)
            a, b = isogrid.cell_at(x, y, self._cell_w, self._cell_h)
            if (a, b) in self._selected:
                self._drag_candidate = True
                self._drag_origin = pos
                event.accept()
                return
        # Otherwise start an area selection. Shift accumulates onto the existing
        # selection (click cells one by one or add another area); a plain press
        # replaces the selection.
        if shift:
            self._mode = "add"
            self._base_selected = set(self._selected)
        else:
            self._mode = "replace"
            self._base_selected = set()
        self._selecting = True
        self._press = pos
        self._cur = pos
        self._recompute_selection()
        event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._drag_candidate:
            if (
                event.position() - self._drag_origin
            ).manhattanLength() > self.DRAG_THRESHOLD:
                self._drag_candidate = False
                self._start_export_drag()
            event.accept()
            return
        if self._selecting:
            self._cur = event.position()
            self._recompute_selection()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _start_export_drag(self) -> None:
        """Start a QDrag carrying the current selection for a preview drop."""
        if not self._selected:
            return
        # Ask the panel to copy the selection to the clipboard (drop pastes it).
        self.prepare_drag.emit()
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setData(MIME_CELLS, b"1")
        drag.setMimeData(mime)
        drag.exec(QtCore.Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._drag_candidate and event.button() == QtCore.Qt.MouseButton.LeftButton:
            # A click on the selection without dragging: no-op (keep selection).
            self._drag_candidate = False
            self._drag_origin = None
            event.accept()
            return
        if self._selecting and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._cur = event.position()
            self._recompute_selection()
            self._selecting = False
            self._press = None
            self._cur = None
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _recompute_selection(self) -> None:
        pick = isogrid.cells_in_rect if self._select_shape == "rect" else isogrid.cells_in_diamond
        cells = pick(
            self._to_image(self._press),
            self._to_image(self._cur),
            self._cell_w,
            self._cell_h,
            self._img_w,
            self._img_h,
        )
        if self._mode == "add":
            self._selected = self._base_selected | set(cells)
        else:
            self._selected = set(cells)
        self.selection_changed.emit(len(self._selected))
        self.update()

    def _clear_selection(self) -> None:
        self._selecting = False
        self._press = None
        self._cur = None
        self._base_selected = set()
        self._mode = "replace"
        self._drag_candidate = False
        self._drag_origin = None
        if self._selected:
            self._selected = set()
        self.selection_changed.emit(0)


class EditorPanel(QtWidgets.QWidget):
    """The left tile-editor panel wiring the canvas to the shared state."""

    def __init__(self, state: AppState, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.state = state
        self._build_ui()
        self._connect()
        self._sync_grid()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # Command row.
        cmd = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton("Add image")
        self.paste_image_button = QtWidgets.QPushButton("Paste image")
        self.paste_image_button.setToolTip(
            "Add the image on the clipboard as a new source (Cmd/Ctrl+Shift+V)"
        )
        self.remove_button = QtWidgets.QPushButton("Remove image")
        cmd.addWidget(self.add_button)
        cmd.addWidget(self.paste_image_button)
        cmd.addWidget(self.remove_button)
        cmd.addSpacing(12)
        cmd.addWidget(QtWidgets.QLabel("Split:"))
        self.width_spin = QtWidgets.QSpinBox()
        self.width_spin.setRange(2, 4096)
        self.width_spin.setValue(self.state.cell_w)
        self.height_spin = QtWidgets.QSpinBox()
        self.height_spin.setRange(2, 4096)
        self.height_spin.setValue(self.state.cell_h)
        cmd.addWidget(self.width_spin)
        cmd.addWidget(QtWidgets.QLabel("x"))
        cmd.addWidget(self.height_spin)
        self.split_button = QtWidgets.QPushButton("Split Grid")
        cmd.addWidget(self.split_button)
        cmd.addSpacing(12)
        cmd.addWidget(QtWidgets.QLabel("Select:"))
        self.shape_combo = QtWidgets.QComboBox()
        self.shape_combo.addItem("Diamond", "diamond")
        self.shape_combo.addItem("Rect", "rect")
        self.shape_combo.setToolTip(
            "Drag-select shape: Diamond (isometric area) or Rect (screen rectangle)"
        )
        cmd.addWidget(self.shape_combo)
        cmd.addSpacing(12)
        self.copy_button = QtWidgets.QPushButton("Copy")
        self.copy_button.setToolTip(
            "Copy the selected diamond cells to the clipboard (Cmd/Ctrl+C)"
        )
        self.copy_button.setEnabled(False)
        cmd.addWidget(self.copy_button)
        cmd.addStretch(1)
        layout.addLayout(cmd)

        # Image list + canvas.
        self.image_list = QtWidgets.QListWidget()
        self.image_list.setMaximumHeight(96)
        layout.addWidget(self.image_list)

        self.canvas = EditorCanvas()
        layout.addWidget(self.canvas, 1)

        self.hint = QtWidgets.QLabel(
            "Add / drop / paste an image → Split Grid → select (drag / click / "
            "Shift+click) → Copy (Cmd/Ctrl+C) or drag the selection onto the preview"
        )
        self.hint.setStyleSheet("color: #999;")
        layout.addWidget(self.hint)

    def _connect(self) -> None:
        self.add_button.clicked.connect(self._on_add)
        self.paste_image_button.clicked.connect(self.paste_clipboard_image)
        self.remove_button.clicked.connect(self._on_remove)
        # Drag image files or an image onto the canvas to add sources.
        self.canvas.files_dropped.connect(self._on_files_dropped)
        self.canvas.image_dropped.connect(self._on_image_dropped)
        self.split_button.clicked.connect(self._on_split)
        self.shape_combo.currentIndexChanged.connect(self._on_shape_changed)
        self.copy_button.clicked.connect(self.copy_selection)
        self.image_list.currentRowChanged.connect(self.state.select_source)
        self.canvas.selection_changed.connect(
            lambda n: self.copy_button.setEnabled(n > 0)
        )
        # Dragging the selection out copies it first, then the preview drop pastes.
        self.canvas.prepare_drag.connect(self.copy_selection)
        self.state.sources_changed.connect(self._rebuild_list)
        self.state.source_selected.connect(self._on_source_selected)
        self.state.grid_changed.connect(self._sync_grid)

    # -- Command handlers ----------------------------------------------
    def _on_add(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Add images",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*)",
        )
        for p in paths:
            self.state.add_source(p)

    def paste_clipboard_image(self) -> bool:
        """Add the clipboard's image as a new source (button / Cmd+Shift+V)."""
        clipboard = QtWidgets.QApplication.clipboard()
        qimg = clipboard.image()
        if qimg is None or qimg.isNull():
            return False
        self.state.add_source_image(qimage_to_pil(qimg), "Pasted image")
        return True

    def _on_files_dropped(self, paths) -> None:
        for p in paths:
            self.state.add_source(p)

    def _on_image_dropped(self, image) -> None:
        self.state.add_source_image(image, "Dropped image")

    def _on_remove(self) -> None:
        row = self.image_list.currentRow()
        if row >= 0:
            self.state.remove_source(row)

    def _on_split(self) -> None:
        self.state.set_cell_size(self.width_spin.value(), self.height_spin.value())
        # set_cell_size only emits when the size changed; make sure the grid is
        # shown (and selection reset) even when the size is unchanged.
        self._sync_grid()

    def _on_shape_changed(self) -> None:
        self.canvas.set_select_shape(self.shape_combo.currentData())

    def copy_selection(self) -> None:
        """Copy the editor's selected cells to the clipboard (button / Cmd+C)."""
        src = self.state.selected_source()
        if src is None:
            return
        items = []
        for a, b in self.canvas.selected_cells():
            cell = isogrid.cell_image(src.image, a, b, self.state.cell_w, self.state.cell_h)
            if cell is None:
                continue
            # Isometric tile coords so the preview reproduces the diamond shape.
            col = (a + b) // 2
            row = (b - a) // 2
            items.append((col, row, cell))
        if items:
            self.state.copy_cells(items)

    # -- State reactions -----------------------------------------------
    def _rebuild_list(self) -> None:
        self.image_list.blockSignals(True)
        self.image_list.clear()
        for src in self.state.sources:
            self.image_list.addItem(src.name)
        sel = self.state.selected_index
        if 0 <= sel < self.image_list.count():
            self.image_list.setCurrentRow(sel)
        self.image_list.blockSignals(False)

    def _on_source_selected(self, index: int) -> None:
        if self.image_list.currentRow() != index and 0 <= index < self.image_list.count():
            self.image_list.blockSignals(True)
            self.image_list.setCurrentRow(index)
            self.image_list.blockSignals(False)
        src = self.state.selected_source()
        self.canvas.set_image(src.image if src is not None else None)
        self._sync_grid()

    def _sync_grid(self) -> None:
        self.width_spin.blockSignals(True)
        self.height_spin.blockSignals(True)
        self.width_spin.setValue(self.state.cell_w)
        self.height_spin.setValue(self.state.cell_h)
        self.width_spin.blockSignals(False)
        self.height_spin.blockSignals(False)
        # Grid is shown whenever a source image is present.
        self.canvas.set_grid(self.state.cell_w, self.state.cell_h, self.state.selected_source() is not None)
