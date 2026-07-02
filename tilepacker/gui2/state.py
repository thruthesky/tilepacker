"""Application state for the minimal (gui2) tilepacker app.

:class:`AppState` is the single source of truth shared by the editor and the
tileset preview. It holds the imported source images, the isometric split-grid
size, the tileset (a sparse ``(col, row) -> tile`` grid), and the copy/paste
clipboard, and emits Qt signals when any of these change.

The tileset is a *grid*, not a flat list: a tile keeps the isometric column/row
it was copied from so the preview reproduces exactly the diamond shape selected
in the editor. Copy records each cell's relative ``(col, row)`` (normalized so
the top-left cell is ``(0, 0)``) plus its image. Paste places the clipboard at
an anchor cell (a click in the preview) or at the origin, overwriting whatever
sits at each target cell -- so pasting one copied cell replaces exactly one cell.

Isometric tile coords are derived from the diamond lattice index ``(a, b)`` as
``col = (a + b) / 2`` (down-right axis) and ``row = (b - a) / 2`` (down-left
axis); with these, ``screen = ((col - row) * hw, (col + row) * hh)`` matches the
editor's on-screen cell positions.

Workspaces are saved as a self-contained JSON file: source images are stored by
path (re-loaded if still present) and grid tiles are inlined as base64 PNGs.
"""

from __future__ import annotations

import base64
import io
import json
import os
from typing import Dict, List, Optional, Tuple

from PIL import Image
from PySide6 import QtCore

__all__ = ["SourceImage", "AppState"]

#: Default isometric cell size (Tiled's classic 2:1 diamond).
DEFAULT_CELL_W = 64
DEFAULT_CELL_H = 32
#: Workspace file format version.
WORKSPACE_VERSION = 2

#: A clipboard entry: relative column, relative row, and the cell image.
ClipCell = Tuple[int, int, Image.Image]
#: A grid coordinate: (column, row).
Cell = Tuple[int, int]


class SourceImage:
    """One imported source image: its file path and the loaded RGBA pixels."""

    def __init__(self, path: str, image: Image.Image):
        self.path = path
        self.image = image.convert("RGBA")

    @property
    def name(self) -> str:
        """Return the file's base name (shown in the image list)."""
        return os.path.basename(self.path) or self.path


def _png_to_b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGBA").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _b64_to_png(data: str) -> Image.Image:
    raw = base64.b64decode(data.encode("ascii"))
    return Image.open(io.BytesIO(raw)).convert("RGBA")


class AppState(QtCore.QObject):
    """Shared, observable state for the minimal tilepacker app."""

    #: The source image list changed (added / removed).
    sources_changed = QtCore.Signal()
    #: The selected source image changed. Carries the new index (or -1).
    source_selected = QtCore.Signal(int)
    #: The split-grid cell size changed.
    grid_changed = QtCore.Signal()
    #: The tileset grid changed (pasted / cleared / loaded / tile removed).
    tiles_changed = QtCore.Signal()
    #: The clipboard changed (copied / cleared). Carries the clipboard size.
    clipboard_changed = QtCore.Signal(int)
    #: The undo availability changed. Carries True when an undo step exists.
    undo_changed = QtCore.Signal(bool)

    #: Maximum number of undo steps kept for the tileset grid.
    MAX_UNDO = 50

    def __init__(self, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self._sources: List[SourceImage] = []
        self._selected = -1
        self._cell_w = DEFAULT_CELL_W
        self._cell_h = DEFAULT_CELL_H
        self._grid: Dict[Cell, Image.Image] = {}
        self._clipboard: List[ClipCell] = []
        #: Snapshots of ``_grid`` taken before each mutation (paste/remove/clear).
        self._undo_stack: List[Dict[Cell, Image.Image]] = []

    # -- Source images --------------------------------------------------
    @property
    def sources(self) -> List[SourceImage]:
        return self._sources

    @property
    def selected_index(self) -> int:
        return self._selected

    def selected_source(self) -> Optional[SourceImage]:
        if 0 <= self._selected < len(self._sources):
            return self._sources[self._selected]
        return None

    def add_source(self, path: str) -> Optional[SourceImage]:
        try:
            img = Image.open(path)
            img.load()
        except Exception:
            return None
        src = SourceImage(path, img)
        self._sources.append(src)
        self.sources_changed.emit()
        self.select_source(len(self._sources) - 1)
        return src

    def remove_source(self, index: int) -> None:
        if not (0 <= index < len(self._sources)):
            return
        del self._sources[index]
        self.sources_changed.emit()
        new_sel = min(index, len(self._sources) - 1)
        self._selected = -1
        self.select_source(new_sel)

    def select_source(self, index: int) -> None:
        idx = index if 0 <= index < len(self._sources) else -1
        if idx != self._selected:
            self._selected = idx
            self.source_selected.emit(idx)

    # -- Split grid -----------------------------------------------------
    @property
    def cell_w(self) -> int:
        return self._cell_w

    @property
    def cell_h(self) -> int:
        return self._cell_h

    def set_cell_size(self, width: int, height: int) -> None:
        w = max(2, int(width))
        h = max(2, int(height))
        if (w, h) != (self._cell_w, self._cell_h):
            self._cell_w = w
            self._cell_h = h
            self.grid_changed.emit()

    # -- Tileset grid & clipboard --------------------------------------
    @property
    def grid(self) -> Dict[Cell, Image.Image]:
        return self._grid

    @property
    def clipboard(self) -> List[ClipCell]:
        return self._clipboard

    @property
    def tile_count(self) -> int:
        return len(self._grid)

    def grid_bounds(self) -> Optional[Tuple[int, int, int, int]]:
        """Return ``(min_col, min_row, max_col, max_row)`` of the grid, or None."""
        if not self._grid:
            return None
        cols = [c for c, _ in self._grid]
        rows = [r for _, r in self._grid]
        return (min(cols), min(rows), max(cols), max(rows))

    def copy_cells(self, items: List[ClipCell]) -> None:
        """Put copied cells on the clipboard as ``(rel_col, rel_row, image)``.

        The relative coordinates are normalized so the top-left copied cell is
        ``(0, 0)``; this preserves the diamond shape when pasting.
        """
        if not items:
            self._clipboard = []
            self.clipboard_changed.emit(0)
            return
        min_c = min(c for c, _, _ in items)
        min_r = min(r for _, r, _ in items)
        self._clipboard = [
            (c - min_c, r - min_r, im.convert("RGBA")) for c, r, im in items
        ]
        self.clipboard_changed.emit(len(self._clipboard))

    def paste(self, anchor: Optional[Cell] = None) -> int:
        """Place the clipboard into the grid at ``anchor`` (or the origin).

        Each clipboard cell is written to ``(anchor + rel)``, overwriting any
        existing tile there. Returns how many cells were placed.
        """
        if not self._clipboard:
            return 0
        self._push_undo()
        base_col, base_row = anchor if anchor is not None else (0, 0)
        for dcol, drow, img in self._clipboard:
            self._grid[(base_col + dcol, base_row + drow)] = img.convert("RGBA")
        self.tiles_changed.emit()
        return len(self._clipboard)

    def remove_at(self, cell: Cell) -> bool:
        """Remove the tile at ``cell`` if present. Returns True when removed."""
        if cell in self._grid:
            self._push_undo()
            del self._grid[cell]
            self.tiles_changed.emit()
            return True
        return False

    def clear_tiles(self) -> None:
        if self._grid:
            self._push_undo()
            self._grid = {}
            self.tiles_changed.emit()

    # -- Undo -----------------------------------------------------------
    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def _push_undo(self) -> None:
        """Snapshot the grid before a mutation so it can be undone."""
        self._undo_stack.append(dict(self._grid))
        if len(self._undo_stack) > self.MAX_UNDO:
            self._undo_stack.pop(0)
        self.undo_changed.emit(True)

    def undo(self) -> bool:
        """Restore the grid to before the last mutation. Returns True if undone."""
        if not self._undo_stack:
            return False
        self._grid = self._undo_stack.pop()
        self.tiles_changed.emit()
        self.undo_changed.emit(bool(self._undo_stack))
        return True

    def ordered_tiles(self) -> Tuple[List[Image.Image], int, int]:
        """Return ``(tiles, columns, rows)`` for export.

        The grid's bounding box is walked row-major; empty cells become fully
        transparent tiles so the packed tileset stays a uniform rectangle whose
        cell positions match the preview / editor layout.
        """
        bounds = self.grid_bounds()
        if bounds is None:
            return [], 0, 0
        min_c, min_r, max_c, max_r = bounds
        cols = max_c - min_c + 1
        rows = max_r - min_r + 1
        empty = Image.new("RGBA", (self._cell_w, self._cell_h), (0, 0, 0, 0))
        tiles: List[Image.Image] = []
        for row in range(min_r, max_r + 1):
            for col in range(min_c, max_c + 1):
                tiles.append(self._grid.get((col, row), empty))
        return tiles, cols, rows

    # -- Workspace save / load ------------------------------------------
    def to_workspace(self) -> dict:
        return {
            "version": WORKSPACE_VERSION,
            "cell_w": self._cell_w,
            "cell_h": self._cell_h,
            "sources": [s.path for s in self._sources],
            "grid": [
                {"c": c, "r": r, "png": _png_to_b64(img)}
                for (c, r), img in sorted(self._grid.items(), key=lambda kv: (kv[0][1], kv[0][0]))
            ],
        }

    def save_workspace(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_workspace(), fh)

    def load_workspace(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self._cell_w = max(2, int(data.get("cell_w", DEFAULT_CELL_W)))
        self._cell_h = max(2, int(data.get("cell_h", DEFAULT_CELL_H)))
        self._sources = []
        for p in data.get("sources", []):
            try:
                img = Image.open(p)
                img.load()
                self._sources.append(SourceImage(p, img))
            except Exception:
                continue
        self._grid = {}
        for entry in data.get("grid", []):
            try:
                self._grid[(int(entry["c"]), int(entry["r"]))] = _b64_to_png(entry["png"])
            except Exception:
                continue
        self._selected = 0 if self._sources else -1
        self._clipboard = []
        self._undo_stack = []
        self.sources_changed.emit()
        self.grid_changed.emit()
        self.tiles_changed.emit()
        self.clipboard_changed.emit(0)
        self.undo_changed.emit(False)
        self.source_selected.emit(self._selected)
