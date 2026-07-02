"""Right panel: the isometric tileset preview for the minimal (gui2) app.

The preview draws the tileset *grid* (``(col, row) -> tile``) with the standard
isometric projection, so it reproduces exactly the diamond shape selected in the
editor. Click a cell to set the paste anchor (highlighted); Paste then writes the
clipboard at that anchor -- pasting a single copied cell replaces exactly one
cell. With no anchor, Paste lands at the grid origin (preserving the copied
shape). The cell width/height is shared with the editor's split grid.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets

from tilepacker.gui2 import isogrid
from tilepacker.gui2.qtutil import pil_to_qpixmap
from tilepacker.gui2.state import AppState

__all__ = ["TilesetPanel", "TilesetCanvas"]

Cell = Tuple[int, int]


class TilesetCanvas(QtWidgets.QWidget):
    """Paints the tileset grid in an auto-fitted isometric layout.

    Emits :attr:`cell_clicked` with the ``(col, row)`` of a clicked cell so the
    panel can use it as the paste anchor.
    """

    BACKGROUND = QtGui.QColor("#222222")
    GRID_COLOR = QtGui.QColor(255, 255, 255, 55)
    ANCHOR_LINE = QtGui.QColor(255, 122, 0)
    ANCHOR_FILL = QtGui.QColor(255, 122, 0, 60)
    PADDING = 12
    PLACEHOLDER = "Copy cells in the editor, then Paste here"

    cell_clicked = QtCore.Signal(int, int)
    #: Emitted on Delete/Backspace with an anchor set: the cell to remove.
    delete_requested = QtCore.Signal(int, int)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._grid: Dict[Cell, QtGui.QPixmap] = {}
        self._bounds: Optional[Tuple[int, int, int, int]] = None
        self._cell_w = 64
        self._cell_h = 32
        self._anchor: Optional[Cell] = None
        # Last-paint geometry for click hit-testing: (base_x, base_y, scale,
        # min_x, min_y). None until painted with a non-empty grid.
        self._geom: Optional[Tuple[float, float, float, float, float]] = None
        self.setMinimumSize(320, 300)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    def set_grid(self, grid: Dict[Cell, Image.Image], cell_w: int, cell_h: int) -> None:
        self._grid = {cell: pil_to_qpixmap(img) for cell, img in grid.items()}
        self._cell_w = max(2, int(cell_w))
        self._cell_h = max(2, int(cell_h))
        if self._grid:
            cols = [c for c, _ in self._grid]
            rows = [r for _, r in self._grid]
            self._bounds = (min(cols), min(rows), max(cols), max(rows))
        else:
            self._bounds = None
            self._anchor = None
        self.update()

    def set_anchor(self, cell: Optional[Cell]) -> None:
        if cell != self._anchor:
            self._anchor = cell
            self.update()

    def anchor(self) -> Optional[Cell]:
        return self._anchor

    def rows(self) -> int:
        if self._bounds is None:
            return 0
        return self._bounds[3] - self._bounds[1] + 1

    def cols(self) -> int:
        if self._bounds is None:
            return 0
        return self._bounds[2] - self._bounds[0] + 1

    # -- Painting -------------------------------------------------------
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        try:
            painter.fillRect(self.rect(), self.BACKGROUND)
            if not self._grid:
                self._geom = None
                painter.setPen(QtGui.QColor("#aaaaaa"))
                painter.drawText(
                    self.rect(),
                    int(QtCore.Qt.AlignmentFlag.AlignCenter),
                    self.PLACEHOLDER,
                )
                return
            self._paint_grid(painter)
        finally:
            painter.end()

    def _paint_grid(self, painter: QtGui.QPainter) -> None:
        tw = self._cell_w
        th = self._cell_h
        hw = tw / 2.0
        hh = th / 2.0

        def top_left(col: int, row: int) -> Tuple[float, float]:
            return ((col - row) * hw, (col + row) * hh)

        # Bounding box over every cell (min .. max).
        min_c, min_r, max_c, max_r = self._bounds
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for col in range(min_c, max_c + 1):
            for row in range(min_r, max_r + 1):
                sx, sy = top_left(col, row)
                min_x = min(min_x, sx)
                min_y = min(min_y, sy)
                max_x = max(max_x, sx + tw)
                max_y = max(max_y, sy + th)

        layout_w = max(1.0, max_x - min_x)
        layout_h = max(1.0, max_y - min_y)
        pad = self.PADDING
        aw = max(1, self.width() - 2 * pad)
        ah = max(1, self.height() - 2 * pad)
        scale = min(aw / layout_w, ah / layout_h)
        base_x = pad + (aw - layout_w * scale) / 2.0
        base_y = pad + (ah - layout_h * scale) / 2.0
        self._geom = (base_x, base_y, scale, min_x, min_y)

        cell_w = tw * scale
        cell_h = th * scale
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        def cell_rect(col: int, row: int) -> QtCore.QRectF:
            sx, sy = top_left(col, row)
            return QtCore.QRectF(
                base_x + (sx - min_x) * scale,
                base_y + (sy - min_y) * scale,
                cell_w,
                cell_h,
            )

        def diamond(rect: QtCore.QRectF) -> QtGui.QPolygonF:
            return QtGui.QPolygonF(
                [
                    QtCore.QPointF(rect.center().x(), rect.top()),
                    QtCore.QPointF(rect.right(), rect.center().y()),
                    QtCore.QPointF(rect.center().x(), rect.bottom()),
                    QtCore.QPointF(rect.left(), rect.center().y()),
                ]
            )

        # Draw tiles in reading order (back-to-front) so overlaps look right.
        for row in range(min_r, max_r + 1):
            for col in range(min_c, max_c + 1):
                pm = self._grid.get((col, row))
                rect = cell_rect(col, row)
                if pm is not None:
                    painter.drawPixmap(rect, pm, QtCore.QRectF(pm.rect()))
                    painter.setPen(QtGui.QPen(self.GRID_COLOR, 1))
                    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                    painter.drawPolygon(diamond(rect))

        # Anchor highlight (paste target).
        if self._anchor is not None:
            painter.setPen(QtGui.QPen(self.ANCHOR_LINE, 2))
            painter.setBrush(self.ANCHOR_FILL)
            painter.drawPolygon(diamond(cell_rect(*self._anchor)))

    # -- Interaction ----------------------------------------------------
    def _cell_at(self, pos: QtCore.QPointF) -> Optional[Cell]:
        """Return the ``(col, row)`` grid cell under widget point ``pos``."""
        if self._geom is None:
            return None
        base_x, base_y, scale, min_x, min_y = self._geom
        if scale <= 0:
            return None
        hw = self._cell_w / 2.0
        hh = self._cell_h / 2.0
        # Widget -> layout (top-left/diamond space), then to lattice centre.
        lx = (pos.x() - base_x) / scale + min_x
        ly = (pos.y() - base_y) / scale + min_y
        a, b = isogrid.cell_at(lx - hw, ly - hh, self._cell_w, self._cell_h)
        return ((a + b) // 2, (b - a) // 2)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._grid:
            self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
            cell = self._cell_at(event.position())
            if cell is not None:
                self.set_anchor(cell)
                self.cell_clicked.emit(cell[0], cell[1])
                event.accept()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802
        """Delete / Backspace removes the tile at the selected anchor cell."""
        if (
            event.key() in (QtCore.Qt.Key.Key_Delete, QtCore.Qt.Key.Key_Backspace)
            and self._anchor is not None
        ):
            self.delete_requested.emit(self._anchor[0], self._anchor[1])
            event.accept()
            return
        super().keyPressEvent(event)


class TilesetPanel(QtWidgets.QWidget):
    """The right tileset-preview panel wiring the canvas to the shared state."""

    def __init__(self, state: AppState, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.state = state
        self._build_ui()
        self._connect()
        self._sync_all()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        cmd = QtWidgets.QHBoxLayout()
        cmd.addWidget(QtWidgets.QLabel("Cell:"))
        self.width_spin = QtWidgets.QSpinBox()
        self.width_spin.setRange(2, 4096)
        self.width_spin.setValue(self.state.cell_w)
        self.height_spin = QtWidgets.QSpinBox()
        self.height_spin.setRange(2, 4096)
        self.height_spin.setValue(self.state.cell_h)
        cmd.addWidget(self.width_spin)
        cmd.addWidget(QtWidgets.QLabel("x"))
        cmd.addWidget(self.height_spin)
        cmd.addSpacing(10)
        self.size_label = QtWidgets.QLabel("Grid: 0 x 0")
        cmd.addWidget(self.size_label)
        cmd.addSpacing(10)
        self.paste_button = QtWidgets.QPushButton("Paste")
        self.paste_button.setToolTip(
            "Paste the copied cells at the clicked anchor cell, or the origin "
            "(Cmd/Ctrl+V)"
        )
        self.paste_button.setEnabled(False)
        cmd.addWidget(self.paste_button)
        self.delete_button = QtWidgets.QPushButton("Delete cell")
        self.delete_button.setToolTip("Delete the selected (clicked) cell (Delete)")
        self.delete_button.setEnabled(False)
        cmd.addWidget(self.delete_button)
        self.undo_button = QtWidgets.QPushButton("Undo")
        self.undo_button.setToolTip("Undo the last tileset change (Cmd/Ctrl+Z)")
        self.undo_button.setEnabled(False)
        cmd.addWidget(self.undo_button)
        self.clear_button = QtWidgets.QPushButton("Clear")
        cmd.addWidget(self.clear_button)
        cmd.addStretch(1)
        layout.addLayout(cmd)

        self.canvas = TilesetCanvas()
        layout.addWidget(self.canvas, 1)

        self.count_label = QtWidgets.QLabel("0 tiles")
        self.count_label.setStyleSheet("color: #999;")
        layout.addWidget(self.count_label)

    def _connect(self) -> None:
        self.width_spin.valueChanged.connect(self._on_cell_size)
        self.height_spin.valueChanged.connect(self._on_cell_size)
        self.paste_button.clicked.connect(self.paste_clipboard)
        self.delete_button.clicked.connect(self.delete_selected)
        self.undo_button.clicked.connect(self.state.undo)
        self.clear_button.clicked.connect(self.state.clear_tiles)
        self.canvas.cell_clicked.connect(self._on_cell_clicked)
        self.canvas.delete_requested.connect(lambda c, r: self.state.remove_at((c, r)))
        self.state.tiles_changed.connect(self._sync_tiles)
        self.state.grid_changed.connect(self._sync_grid)
        self.state.clipboard_changed.connect(
            lambda n: self.paste_button.setEnabled(n > 0)
        )
        self.state.undo_changed.connect(self.undo_button.setEnabled)

    # -- Handlers -------------------------------------------------------
    def _on_cell_size(self) -> None:
        self.state.set_cell_size(self.width_spin.value(), self.height_spin.value())

    def paste_clipboard(self) -> None:
        """Paste the clipboard at the clicked anchor / origin (button / Cmd+V)."""
        if not self.state.clipboard:
            return
        self.state.paste(self.canvas.anchor())

    def delete_selected(self) -> None:
        """Delete the tile at the selected anchor cell (button / Delete key)."""
        anchor = self.canvas.anchor()
        if anchor is not None:
            self.state.remove_at(anchor)

    def _on_cell_clicked(self, col: int, row: int) -> None:
        # A cell is now the anchor: enable deleting it.
        self.delete_button.setEnabled(self.state.grid.get((col, row)) is not None)

    # -- State reactions -----------------------------------------------
    def _sync_all(self) -> None:
        self._sync_grid()
        self._sync_tiles()
        self.paste_button.setEnabled(bool(self.state.clipboard))

    def _sync_grid(self) -> None:
        self.width_spin.blockSignals(True)
        self.height_spin.blockSignals(True)
        self.width_spin.setValue(self.state.cell_w)
        self.height_spin.setValue(self.state.cell_h)
        self.width_spin.blockSignals(False)
        self.height_spin.blockSignals(False)
        self.canvas.set_grid(self.state.grid, self.state.cell_w, self.state.cell_h)
        self._sync_labels()

    def _sync_tiles(self) -> None:
        self.canvas.set_grid(self.state.grid, self.state.cell_w, self.state.cell_h)
        self._sync_labels()

    def _sync_labels(self) -> None:
        self.count_label.setText(f"{self.state.tile_count} tiles")
        self.size_label.setText(f"Grid: {self.canvas.cols()} x {self.canvas.rows()}")
        # A cell can be deleted only when the anchor still holds a tile.
        anchor = self.canvas.anchor()
        self.delete_button.setEnabled(
            anchor is not None and self.state.grid.get(anchor) is not None
        )
        self.undo_button.setEnabled(self.state.can_undo)
