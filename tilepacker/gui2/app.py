"""Main window and launcher for the minimal (gui2) tilepacker app.

Layout: a horizontal splitter with the isometric tile editor on the left and
the isometric tileset preview on the right, plus a menu bar and toolbar for the
tilepacker-level actions:

* Export  - write the collected tiles to a tileset PNG + isometric ``.tsx``.
* Import  - load a previously saved workspace (``.json``).
* Save    - save the current workspace (source list, grid, collected tiles).

Every command is a window-owned ``QAction`` placed in the File / Edit / View /
Help menus (macOS merges them into the system menu bar; other platforms show
them in-window) and reused by the toolbar, so each behavior has exactly one
binding — no bare ``QShortcut`` may coexist with an action on the same keys.

PySide6 is imported here (not at package import time) so the pure logic modules
stay usable headless.
"""

from __future__ import annotations

import os
import sys
from typing import Optional, Sequence

from PySide6 import QtGui, QtWidgets

from tilepacker.core.config import PackConfig
from tilepacker.core.export import export_tileset
from tilepacker.core.tiled import write_tmx
from tilepacker.gui2.editor import EditorPanel
from tilepacker.gui2.state import AppState
from tilepacker.gui2.tileset import TilesetPanel

__all__ = ["MinimalWindow", "launch"]

APP_NAME = "tilepacker"
APP_DISPLAY_NAME = "Tile Packer"


class MinimalWindow(QtWidgets.QMainWindow):
    """The minimal two-panel tilepacker window."""

    def __init__(self, state: Optional[AppState] = None):
        super().__init__()
        self.setWindowTitle("tilepacker (minimal)")
        self.state = state or AppState(self)

        splitter = QtWidgets.QSplitter()
        self.editor = EditorPanel(self.state)
        self.tileset = TilesetPanel(self.state)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.tileset)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)
        self.resize(1200, 720)
        self._build_menus()
        self._build_toolbar()
        self.statusBar().showMessage("Add an image to begin")

    def _build_menus(self) -> None:
        """Create the window-owned actions and the File/Edit/View/Help menus.

        The actions carry every key binding (standard keys map to Cmd on macOS
        and Ctrl elsewhere) and are shared with the toolbar; nothing else may
        register the same shortcuts.
        """
        # File: workspace in/out, tileset export, close/quit.
        self.import_action = QtGui.QAction("Import Workspace...", self)
        self.import_action.setIconText("Import")
        self.import_action.setStatusTip("Load a previously saved .json workspace")
        self.import_action.setShortcut(QtGui.QKeySequence.StandardKey.Open)
        self.import_action.triggered.connect(self._on_import)
        self.save_workspace_action = QtGui.QAction("Save Workspace...", self)
        self.save_workspace_action.setIconText("Save workspace")
        self.save_workspace_action.setStatusTip(
            "Save the current workspace (sources, grid, collected tiles)"
        )
        self.save_workspace_action.setShortcut(QtGui.QKeySequence.StandardKey.Save)
        self.save_workspace_action.triggered.connect(self._on_save_workspace)
        self.export_action = QtGui.QAction("Export Tileset...", self)
        self.export_action.setIconText("Export")
        self.export_action.setStatusTip(
            "Export the tileset PNG + .tsx and the isometric .tmx map"
        )
        self.export_action.setShortcut(QtGui.QKeySequence("Ctrl+E"))
        self.export_action.triggered.connect(self._on_export)
        self.close_action = QtGui.QAction("Close Window", self)
        self.close_action.setShortcut(QtGui.QKeySequence.StandardKey.Close)
        self.close_action.triggered.connect(self.close)
        self.quit_action = QtGui.QAction("Quit", self)
        # QuitRole relocates the item into the macOS app menu.
        self.quit_action.setMenuRole(QtGui.QAction.MenuRole.QuitRole)
        self.quit_action.setShortcut(QtGui.QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(QtWidgets.QApplication.closeAllWindows)

        # Edit: undo, copy the editor selection, paste into the tileset
        # preview (at its clicked anchor, or the origin), and Cmd/Ctrl+Shift+V
        # to add the clipboard image as a source (distinct from plain paste).
        self.undo_action = QtGui.QAction("Undo", self)
        self.undo_action.setStatusTip("Undo the last tileset change")
        self.undo_action.setShortcut(QtGui.QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.state.undo)
        self.copy_action = QtGui.QAction("Copy Selection", self)
        self.copy_action.setStatusTip("Copy the selected editor cells")
        self.copy_action.setShortcut(QtGui.QKeySequence.StandardKey.Copy)
        self.copy_action.triggered.connect(self.editor.copy_selection)
        self.paste_action = QtGui.QAction("Paste to Tileset", self)
        self.paste_action.setStatusTip("Paste copied cells into the tileset preview")
        self.paste_action.setShortcut(QtGui.QKeySequence.StandardKey.Paste)
        self.paste_action.triggered.connect(self.tileset.paste_clipboard)
        self.paste_image_action = QtGui.QAction("Paste Image as Source", self)
        self.paste_image_action.setStatusTip("Add the clipboard image as a source")
        self.paste_image_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+V"))
        self.paste_image_action.triggered.connect(self.editor.paste_clipboard_image)

        # View: mirror the tileset panel's "Cell outlines" checkbox; the two
        # stay in sync so the toggle remains single-sourced.
        self.outlines_action = QtGui.QAction("Cell Outlines", self)
        self.outlines_action.setCheckable(True)
        self.outlines_action.setChecked(self.tileset.grid_check.isChecked())
        self.outlines_action.setStatusTip("Outline each cell in the tileset preview")
        self.outlines_action.toggled.connect(self.tileset.grid_check.setChecked)
        self.tileset.grid_check.toggled.connect(self.outlines_action.setChecked)

        # Help: About (AboutRole relocates it into the macOS app menu).
        self.about_action = QtGui.QAction(f"About {APP_DISPLAY_NAME}", self)
        self.about_action.setMenuRole(QtGui.QAction.MenuRole.AboutRole)
        self.about_action.triggered.connect(self._on_about)

        # Menus are created with an explicit Qt parent and kept as attributes:
        # the menuBar().addMenu(str) overload leaves the returned QMenu owned
        # by Python, and shiboken then deletes the C++ menu behind the menu
        # bar's back once transient wrappers (e.g. from actions()) die.
        self.file_menu = QtWidgets.QMenu("File", self)
        self.menuBar().addMenu(self.file_menu)
        self.file_menu.addAction(self.import_action)
        self.file_menu.addAction(self.save_workspace_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.export_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.close_action)
        self.file_menu.addAction(self.quit_action)

        self.edit_menu = QtWidgets.QMenu("Edit", self)
        self.menuBar().addMenu(self.edit_menu)
        self.edit_menu.addAction(self.undo_action)
        self.edit_menu.addSeparator()
        self.edit_menu.addAction(self.copy_action)
        self.edit_menu.addAction(self.paste_action)
        self.edit_menu.addAction(self.paste_image_action)

        self.view_menu = QtWidgets.QMenu("View", self)
        self.menuBar().addMenu(self.view_menu)
        self.view_menu.addAction(self.outlines_action)

        self.help_menu = QtWidgets.QMenu("Help", self)
        self.menuBar().addMenu(self.help_menu)
        self.help_menu.addAction(self.about_action)

    def _build_toolbar(self) -> None:
        # The toolbar reuses the menu actions (short labels via setIconText)
        # so behavior stays single-sourced.
        bar = self.addToolBar("Main")
        bar.setMovable(False)
        bar.addAction(self.export_action)
        bar.addAction(self.import_action)
        bar.addAction(self.save_workspace_action)

    def _on_about(self) -> None:
        QtWidgets.QMessageBox.about(
            self,
            f"About {APP_DISPLAY_NAME}",
            f"{APP_DISPLAY_NAME} (gui2) - a minimal isometric tile editor.\n\n"
            "Cuts diamond tiles from source images and exports a Tiled "
            "tileset (PNG + .tsx) with a matching isometric map (.tmx).",
        )

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


def _macos_set_app_menu_name(name: str) -> None:
    """Rename the macOS application menu for an unbundled interpreter.

    macOS titles the app menu after the running bundle's ``CFBundleName``,
    which is "Python" when gui2 runs from a plain interpreter rather than a
    packaged .app. Patching the in-memory ``NSBundle`` info dictionary before
    the QApplication exists makes the menu read ``name`` instead. Best-effort
    and cosmetic only: a no-op off macOS, when the dictionary is not mutable,
    or when the ObjC runtime is unavailable (e.g. headless CI).
    """
    if sys.platform != "darwin":
        return
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        # Foundation must be loaded for NSBundle/NSString to be registered.
        ctypes.cdll.LoadLibrary(ctypes.util.find_library("Foundation"))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        def send(receiver, selector, *args, types=()):
            # objc_msgSend must be cast per call signature (required on arm64).
            fn = ctypes.CFUNCTYPE(
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, *types
            )(("objc_msgSend", objc))
            return fn(receiver, objc.sel_registerName(selector), *args)

        bundle = send(objc.objc_getClass(b"NSBundle"), b"mainBundle")
        info = send(bundle, b"infoDictionary") if bundle else None
        # Mutating an immutable dictionary would raise an ObjC exception that
        # Python cannot catch, so verify mutability first.
        if not info or not send(
            info,
            b"isKindOfClass:",
            objc.objc_getClass(b"NSMutableDictionary"),
            types=(ctypes.c_void_p,),
        ):
            return
        nsstring = objc.objc_getClass(b"NSString")
        key = send(
            nsstring, b"stringWithUTF8String:", b"CFBundleName",
            types=(ctypes.c_char_p,),
        )
        value = send(
            nsstring, b"stringWithUTF8String:", name.encode("utf-8"),
            types=(ctypes.c_char_p,),
        )
        send(
            info, b"setObject:forKey:", value, key,
            types=(ctypes.c_void_p, ctypes.c_void_p),
        )
    except Exception:
        pass


def _apply_app_identity() -> None:
    """Name the application; must run before the QApplication is created.

    Qt reads these when building the (macOS) menu bar; the app-menu title
    itself comes from the bundle's ``CFBundleName``, patched separately for
    unbundled interpreters.
    """
    _macos_set_app_menu_name(APP_DISPLAY_NAME)
    QtWidgets.QApplication.setApplicationName(APP_NAME)
    QtWidgets.QApplication.setApplicationDisplayName(APP_DISPLAY_NAME)
    QtWidgets.QApplication.setOrganizationName(APP_NAME)


def launch(argv: Optional[Sequence[str]] = None) -> int:
    """Create the application and window and run the Qt event loop."""
    _apply_app_identity()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(list(argv or []))
    window = MinimalWindow()
    window.show()
    return app.exec()
