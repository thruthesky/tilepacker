"""Application state for the minimal (gui2) tilepacker app.

:class:`AppState` is the single source of truth shared by the editor and the
tileset preview. It holds the imported source images, the isometric split-grid
size, the tiles collected into the tileset, and the copy/paste clipboard, and
emits Qt signals when any of these change so the views can refresh.

A "tile" is a finished isometric cell image (a diamond cut from a source, with
everything outside the diamond transparent). Copy puts the selected cells on the
clipboard; Paste appends the clipboard's tiles to the tileset.

Workspaces are saved as a self-contained JSON file: source images are stored by
path (re-loaded if still present) and tiles are inlined as base64 PNGs so the
collected tileset survives even if the source files move.
"""

from __future__ import annotations

import base64
import io
import json
import os
from typing import List, Optional

from PIL import Image
from PySide6 import QtCore

__all__ = ["SourceImage", "AppState"]

#: Default isometric cell size (Tiled's classic 2:1 diamond).
DEFAULT_CELL_W = 64
DEFAULT_CELL_H = 32
#: Default number of tileset columns in the preview / export.
DEFAULT_COLUMNS = 8
#: Workspace file format version.
WORKSPACE_VERSION = 1


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
    """Encode a PIL image as a base64 PNG string."""
    buf = io.BytesIO()
    image.convert("RGBA").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _b64_to_png(data: str) -> Image.Image:
    """Decode a base64 PNG string back into a PIL RGBA image."""
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
    #: The tileset tiles changed (pasted / cleared / loaded).
    tiles_changed = QtCore.Signal()
    #: The clipboard changed (copied / cleared). Carries the clipboard size.
    clipboard_changed = QtCore.Signal(int)
    #: The preview column count changed.
    columns_changed = QtCore.Signal()

    def __init__(self, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self._sources: List[SourceImage] = []
        self._selected = -1
        self._cell_w = DEFAULT_CELL_W
        self._cell_h = DEFAULT_CELL_H
        self._columns = DEFAULT_COLUMNS
        self._tiles: List[Image.Image] = []
        self._clipboard: List[Image.Image] = []

    # -- Source images --------------------------------------------------
    @property
    def sources(self) -> List[SourceImage]:
        return self._sources

    @property
    def selected_index(self) -> int:
        return self._selected

    def selected_source(self) -> Optional[SourceImage]:
        """Return the currently selected source image, or ``None``."""
        if 0 <= self._selected < len(self._sources):
            return self._sources[self._selected]
        return None

    def add_source(self, path: str) -> Optional[SourceImage]:
        """Load ``path`` and append it to the source list; select it.

        Returns the new :class:`SourceImage`, or ``None`` when the file cannot
        be opened.
        """
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
        """Remove the source image at ``index`` from the list."""
        if not (0 <= index < len(self._sources)):
            return
        del self._sources[index]
        self.sources_changed.emit()
        # Keep a valid selection (clamp to the new list length).
        new_sel = min(index, len(self._sources) - 1)
        self._selected = -1  # force a change signal even to the same clamped index
        self.select_source(new_sel)

    def select_source(self, index: int) -> None:
        """Select the source image at ``index`` (``-1`` clears the selection)."""
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
        """Set the isometric split-grid cell size (clamped to >= 2 px)."""
        w = max(2, int(width))
        h = max(2, int(height))
        if (w, h) != (self._cell_w, self._cell_h):
            self._cell_w = w
            self._cell_h = h
            self.grid_changed.emit()

    # -- Preview columns ------------------------------------------------
    @property
    def columns(self) -> int:
        return self._columns

    def set_columns(self, columns: int) -> None:
        """Set the tileset preview / export column count (clamped to >= 1)."""
        c = max(1, int(columns))
        if c != self._columns:
            self._columns = c
            self.columns_changed.emit()

    # -- Tiles & clipboard ----------------------------------------------
    @property
    def tiles(self) -> List[Image.Image]:
        return self._tiles

    @property
    def clipboard(self) -> List[Image.Image]:
        return self._clipboard

    def copy_cells(self, images: List[Image.Image]) -> None:
        """Put ``images`` (already-masked cell tiles) on the clipboard."""
        self._clipboard = [im.convert("RGBA") for im in images]
        self.clipboard_changed.emit(len(self._clipboard))

    def paste(self) -> int:
        """Append the clipboard's tiles to the tileset. Returns how many added."""
        if not self._clipboard:
            return 0
        self._tiles.extend(im.convert("RGBA") for im in self._clipboard)
        self.tiles_changed.emit()
        return len(self._clipboard)

    def remove_tiles(self, indices) -> int:
        """Remove tileset tiles at ``indices``. Returns how many were removed."""
        keep = [t for i, t in enumerate(self._tiles) if i not in set(indices)]
        removed = len(self._tiles) - len(keep)
        if removed:
            self._tiles = keep
            self.tiles_changed.emit()
        return removed

    def clear_tiles(self) -> None:
        """Remove every tile from the tileset."""
        if self._tiles:
            self._tiles = []
            self.tiles_changed.emit()

    # -- Workspace save / load ------------------------------------------
    def to_workspace(self) -> dict:
        """Return a JSON-serializable snapshot of the whole workspace."""
        return {
            "version": WORKSPACE_VERSION,
            "cell_w": self._cell_w,
            "cell_h": self._cell_h,
            "columns": self._columns,
            "sources": [s.path for s in self._sources],
            "tiles": [_png_to_b64(t) for t in self._tiles],
        }

    def save_workspace(self, path: str) -> None:
        """Write the workspace snapshot to ``path`` as JSON."""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_workspace(), fh)

    def load_workspace(self, path: str) -> None:
        """Replace the current state with the workspace stored at ``path``."""
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self._cell_w = max(2, int(data.get("cell_w", DEFAULT_CELL_W)))
        self._cell_h = max(2, int(data.get("cell_h", DEFAULT_CELL_H)))
        self._columns = max(1, int(data.get("columns", DEFAULT_COLUMNS)))
        # Re-load source images that still exist; silently drop missing ones.
        self._sources = []
        for p in data.get("sources", []):
            try:
                img = Image.open(p)
                img.load()
                self._sources.append(SourceImage(p, img))
            except Exception:
                continue
        self._tiles = []
        for b64 in data.get("tiles", []):
            try:
                self._tiles.append(_b64_to_png(b64))
            except Exception:
                continue
        self._selected = 0 if self._sources else -1
        self._clipboard = []
        # Emit everything so all views rebuild from the loaded state.
        self.sources_changed.emit()
        self.grid_changed.emit()
        self.columns_changed.emit()
        self.tiles_changed.emit()
        self.clipboard_changed.emit(0)
        self.source_selected.emit(self._selected)
