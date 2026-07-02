"""Main window and launcher for the minimal (gui2) tilepacker app.

Layout: a horizontal splitter with the isometric tile editor on the left and
the isometric tileset preview on the right, plus a small command bar for the
tilepacker-level actions:

* Export  - write the collected tiles to a tileset PNG + isometric ``.tsx``.
* Import  - load a previously saved workspace (``.json``).
* Save    - save the current workspace (source list, grid, collected tiles).

PySide6 is imported here (not at package import time) so the pure logic modules
stay usable headless.
"""

from __future__ import annotations

import os
from typing import Optional, Sequence

from PySide6 import QtGui, QtWidgets

from tilepacker.core.config import PackConfig
from tilepacker.core.export import export_tileset
from tilepacker.core.tiled import write_tmx
from tilepacker.gui2.editor import EditorPanel
from tilepacker.gui2.state import AppState
from tilepacker.gui2.tileset import TilesetPanel

__all__ = ["MinimalWindow", "launch"]


class MinimalWindow(QtWidgets.QMainWindow):
    """The minimal two-panel tilepacker window."""

    def __init__(self, state: Optional[AppState] = None):
        super().__init__()
        self.setWindowTitle("tilepacker (minimal)")
        self.state = state or AppState(self)

        self._build_toolbar()

        splitter = QtWidgets.QSplitter()
        self.editor = EditorPanel(self.state)
        self.tileset = TilesetPanel(self.state)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.tileset)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)
        self.resize(1200, 720)
        self._build_shortcuts()
        self.statusBar().showMessage("Add an image to begin")

    def _build_shortcuts(self) -> None:
        # Cmd/Ctrl+C copies the editor selection; Cmd/Ctrl+V pastes into the
        # tileset preview (at its clicked anchor, or the origin). Standard keys
        # map to Cmd on macOS and Ctrl elsewhere.
        copy = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Copy, self)
        copy.activated.connect(self.editor.copy_selection)
        paste = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Paste, self)
        paste.activated.connect(self.tileset.paste_clipboard)
        undo = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Undo, self)
        undo.activated.connect(self.state.undo)

    def _build_toolbar(self) -> None:
        bar = self.addToolBar("Main")
        bar.setMovable(False)
        act_export = bar.addAction("Export")
        act_export.triggered.connect(self._on_export)
        act_import = bar.addAction("Import")
        act_import.triggered.connect(self._on_import)
        act_save = bar.addAction("Save workspace")
        act_save.triggered.connect(self._on_save_workspace)

    # -- tilepacker actions --------------------------------------------
    def _on_export(self) -> None:
        # Real tiles + the placement grid, so we can also write an isometric map
        # that reopens in Tiled with the exact editor layout (not just a palette).
        tiles, gids, cols, rows = self.state.map_export_data()
        if not tiles:
            self.statusBar().showMessage("Nothing to export - paste tiles into the tileset first")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export tileset", "tileset.png", "PNG image (*.png)"
        )
        if not path:
            return
        if os.path.splitext(path)[1] == "":
            path += ".png"
        config = PackConfig(
            tile_width=self.state.cell_w,
            tile_height=self.state.cell_h,
            # A packed palette; width doesn't affect the map (gids index by id).
            columns=cols,
        )
        try:
            # Tileset palette is an ORTHOGONAL grid so each tile sits in its own
            # square cell -- easy to tell apart and pick in Tiled's tileset view.
            # The isometric layout lives in the map (.tmx), not the palette.
            result = export_tileset(tiles, config, path, write_tsx=True)
            # Write the isometric map next to the tileset so Tiled shows the
            # original layout: <stem>.tmx referencing <stem>.tsx.
            stem = os.path.splitext(path)[0]
            tmx_path = stem + ".tmx"
            write_tmx(
                tmx_path,
                tileset_source=os.path.basename(result.tsx_path or (stem + ".tsx")),
                columns=cols,
                rows=rows,
                tile_width=self.state.cell_w,
                tile_height=self.state.cell_h,
                gids=gids,
            )
        except Exception as exc:  # pragma: no cover - surfaced to the user
            self.statusBar().showMessage(f"Export failed: {exc}")
            return
        self.statusBar().showMessage(
            f"Exported {result.tile_count} tiles ({cols} x {rows}). "
            f"Open {os.path.basename(tmx_path)} in Tiled for the isometric layout "
            f"({os.path.basename(result.image_path)} + {os.path.basename(result.tsx_path or '')})"
        )

    def _on_import(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Import workspace", "", "Workspace (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            self.state.load_workspace(path)
        except Exception as exc:  # pragma: no cover - surfaced to the user
            self.statusBar().showMessage(f"Import failed: {exc}")
            return
        self.statusBar().showMessage(f"Imported workspace: {os.path.basename(path)}")

    def _on_save_workspace(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save workspace", "workspace.json", "Workspace (*.json)"
        )
        if not path:
            return
        if os.path.splitext(path)[1] == "":
            path += ".json"
        try:
            self.state.save_workspace(path)
        except Exception as exc:  # pragma: no cover - surfaced to the user
            self.statusBar().showMessage(f"Save failed: {exc}")
            return
        self.statusBar().showMessage(f"Saved workspace: {os.path.basename(path)}")


def launch(argv: Optional[Sequence[str]] = None) -> int:
    """Create the application and window and run the Qt event loop."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(list(argv or []))
    window = MinimalWindow()
    window.show()
    return app.exec()
