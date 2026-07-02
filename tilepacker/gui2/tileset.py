"""Right panel: the isometric tileset preview for the minimal (gui2) app.

The preview always draws an isometric (2:1 diamond) layout of the collected
tiles. The command row exposes the cell width/height and the column count; the
row count is derived automatically (``ceil(tile_count / columns)``) and shown
read-only. Paste appends the clipboard's copied cells to the tileset.

The tiles laid out here are exactly what Export writes to the tileset PNG/.tsx.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets

from tilepacker.gui2.qtutil import pil_to_qpixmap
from tilepacker.gui2.state import AppState

__all__ = ["TilesetPanel", "TilesetCanvas"]


class TilesetCanvas(QtWidgets.QWidget):
    """Paints the tiles in an auto-fitted isometric diamond layout."""

    BACKGROUND = QtGui.QColor("#222222")
    GRID_COLOR = QtGui.QColor(255, 255, 255, 55)
    PADDING = 12
    PLACEHOLDER = "Copy cells in the editor, then Paste here"

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._pixmaps: List[QtGui.QPixmap] = []
        self._cell_w = 64
        self._cell_h = 32
        self._columns = 8
        self.setMinimumSize(320, 300)

    def set_tiles(self, tiles: List[Image.Image]) -> None:
        """Replace the previewed tiles."""
        self._pixmaps = [pil_to_qpixmap(t) for t in tiles]
        self.update()

    def set_cell_size(self, cell_w: int, cell_h: int) -> None:
        self._cell_w = max(2, int(cell_w))
        self._cell_h = max(2, int(cell_h))
        self.update()

    def set_columns(self, columns: int) -> None:
        self._columns = max(1, int(columns))
        self.update()

    def rows(self) -> int:
        """Return the auto-derived row count for the current tiles/columns."""
        n = len(self._pixmaps)
        return int(math.ceil(n / self._columns)) if n else 0

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        try:
            painter.fillRect(self.rect(), self.BACKGROUND)
            if not self._pixmaps:
                painter.setPen(QtGui.QColor("#aaaaaa"))
                painter.drawText(
                    self.rect(),
                    int(QtCore.Qt.AlignmentFlag.AlignCenter),
                    self.PLACEHOLDER,
                )
                return
            self._paint_isometric(painter)
        finally:
            painter.end()

    def _paint_isometric(self, painter: QtGui.QPainter) -> None:
        tw = self._cell_w
        th = self._cell_h
        n = len(self._pixmaps)
        cols = self._columns
        rows = self.rows()
        half_w = tw / 2.0
        half_h = th / 2.0

        # First pass: place each tile in iso space and measure the bounding box.
        positions: List[Tuple[float, float]] = []
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
        pad = self.PADDING
        aw = max(1, self.width() - 2 * pad)
        ah = max(1, self.height() - 2 * pad)
        scale = min(aw / layout_w, ah / layout_h)
        base_x = pad + (aw - layout_w * scale) / 2.0
        base_y = pad + (ah - layout_h * scale) / 2.0

        cell_w = tw * scale
        cell_h = th * scale
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        grid_pen = QtGui.QPen(self.GRID_COLOR, 1)
        for i, (sx, sy) in enumerate(positions):
            x = base_x + (sx - min_x) * scale
            y = base_y + (sy - min_y) * scale
            target = QtCore.QRectF(x, y, cell_w, cell_h)
            painter.drawPixmap(
                target, self._pixmaps[i], QtCore.QRectF(self._pixmaps[i].rect())
            )
            painter.setPen(grid_pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPolygon(
                QtGui.QPolygonF(
                    [
                        QtCore.QPointF(x + cell_w / 2.0, y),
                        QtCore.QPointF(x + cell_w, y + cell_h / 2.0),
                        QtCore.QPointF(x + cell_w / 2.0, y + cell_h),
                        QtCore.QPointF(x, y + cell_h / 2.0),
                    ]
                )
            )


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
        cmd.addWidget(QtWidgets.QLabel("Columns:"))
        self.columns_spin = QtWidgets.QSpinBox()
        self.columns_spin.setRange(1, 512)
        self.columns_spin.setValue(self.state.columns)
        cmd.addWidget(self.columns_spin)
        self.rows_label = QtWidgets.QLabel("Rows: 0 (auto)")
        cmd.addWidget(self.rows_label)
        cmd.addSpacing(10)
        self.paste_button = QtWidgets.QPushButton("Paste")
        self.paste_button.setToolTip("Paste the copied cells into the tileset")
        self.paste_button.setEnabled(False)
        cmd.addWidget(self.paste_button)
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
        self.columns_spin.valueChanged.connect(self.state.set_columns)
        self.paste_button.clicked.connect(lambda: self.state.paste())
        self.clear_button.clicked.connect(self.state.clear_tiles)
        self.state.tiles_changed.connect(self._sync_tiles)
        self.state.grid_changed.connect(self._sync_grid)
        self.state.columns_changed.connect(self._sync_columns)
        self.state.clipboard_changed.connect(
            lambda n: self.paste_button.setEnabled(n > 0)
        )

    # -- State reactions -----------------------------------------------
    def _on_cell_size(self) -> None:
        self.state.set_cell_size(self.width_spin.value(), self.height_spin.value())

    def _sync_all(self) -> None:
        self._sync_grid()
        self._sync_columns()
        self._sync_tiles()
        self.paste_button.setEnabled(bool(self.state.clipboard))

    def _sync_grid(self) -> None:
        self.width_spin.blockSignals(True)
        self.height_spin.blockSignals(True)
        self.width_spin.setValue(self.state.cell_w)
        self.height_spin.setValue(self.state.cell_h)
        self.width_spin.blockSignals(False)
        self.height_spin.blockSignals(False)
        self.canvas.set_cell_size(self.state.cell_w, self.state.cell_h)
        self._sync_rows_label()

    def _sync_columns(self) -> None:
        self.columns_spin.blockSignals(True)
        self.columns_spin.setValue(self.state.columns)
        self.columns_spin.blockSignals(False)
        self.canvas.set_columns(self.state.columns)
        self._sync_rows_label()

    def _sync_tiles(self) -> None:
        self.canvas.set_tiles(self.state.tiles)
        self.count_label.setText(f"{len(self.state.tiles)} tiles")
        self._sync_rows_label()

    def _sync_rows_label(self) -> None:
        self.rows_label.setText(f"Rows: {self.canvas.rows()} (auto)")
