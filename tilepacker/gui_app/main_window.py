"""Top-level main window that wires the tilepacker GUI together.

:class:`MainWindow` assembles the tile list, the editor/preview tabs, and the
right-hand grid/edit panels around a single :class:`ProjectModel`. It owns the
import/export flows (file dialogs + ``QMessageBox`` feedback) and keeps every
widget in sync with the model by connecting the child widgets' signals.

All editing, rendering, packing, and color logic is delegated to the model /
``imageedit`` / ``qtutil`` / ``core`` modules; this window only orchestrates.

The window is constructible headless (offscreen): the constructor only builds
widgets and connects signals; it never shows a window or assumes a running
event loop. ``import_images`` / ``export_tileset`` accept explicit arguments so
they can be driven without opening a dialog. All user-facing text is English
(project SSOT).
"""

from __future__ import annotations

import os
from typing import List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from tilepacker.gui_app import qtutil
from tilepacker.gui_app.editor_canvas import EditorCanvas
from tilepacker.gui_app.model import ProjectModel, TileItem
from tilepacker.gui_app.panels import EditPanel, GridPanel
from tilepacker.gui_app.preview_canvas import PreviewCanvas

__all__ = ["MainWindow"]

#: File dialog filter for importable raster images.
_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"

#: File dialog filter for project workspace files.
_WORKSPACE_FILTER = "tilepacker workspace (*.json)"

#: Size (px) of the thumbnail icons shown in the tile list.
_ICON_SIZE = 48


class MainWindow(QtWidgets.QMainWindow):
    """The application's main window: tile list + editor/preview + settings.

    Public API:
        * :meth:`import_images` - load images into the project (dialog or paths).
        * :meth:`export_tileset` - export the tileset PNG + .tsx/.tsj (dialog or path).
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        """Build the window, model, child widgets, menus, and signal wiring."""
        super().__init__(parent)
        self.setWindowTitle("tilepacker")
        # Accept image files dropped onto the window (drag & drop import).
        self.setAcceptDrops(True)

        #: The single source of truth for the whole project.
        self.model = ProjectModel()

        self._build_ui()
        self._build_actions()
        self._connect_signals()

        # Initialize the preview with the model and reflect the empty state.
        self.preview_canvas.set_model(self.model)
        self._sync_selection(None)
        self._update_steps()
        self.statusBar().showMessage(
            "Drag corner handles in Edit to resize "
            "• Tileset Preview shows how tiles span cells."
        )

    # -- Construction ---------------------------------------------------
    def _build_ui(self) -> None:
        """Create the side-by-side central layout and its child widgets.

        Three panes sit next to each other (left to right): the Edit Tile pane
        (with the tile list + management buttons across its top, and the editor
        canvas below), the Tileset Preview pane, and the right-hand settings
        (grid + per-tile edit). The Edit Tile and Tileset Preview are shown at
        the same time rather than as tabs.
        """
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # --- Pane 1: Edit Tile (tile strip + buttons on top, canvas below) ---
        self.editor_canvas = EditorCanvas()
        self.editor_canvas.setToolTip(
            "Drag corner handles to resize the selected tile; drag inside to crop. "
            "Right-click for actions."
        )
        self.editor_canvas.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )

        # The tile list, shown as a horizontal thumbnail strip at the top.
        self.tile_list = QtWidgets.QListWidget()
        self.tile_list.setIconSize(QtCore.QSize(_ICON_SIZE, _ICON_SIZE))
        self.tile_list.setViewMode(QtWidgets.QListWidget.ViewMode.IconMode)
        self.tile_list.setFlow(QtWidgets.QListWidget.Flow.LeftToRight)
        self.tile_list.setWrapping(False)
        self.tile_list.setMovement(QtWidgets.QListWidget.Movement.Static)
        self.tile_list.setResizeMode(QtWidgets.QListWidget.ResizeMode.Adjust)
        self.tile_list.setFixedHeight(_ICON_SIZE + 38)
        self.tile_list.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.tile_list.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.tile_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.tile_list.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.tile_list.setToolTip(
            "Imported tiles (export order, left to right). Right-click for actions."
        )

        btn_row = QtWidgets.QWidget()
        btn_layout = QtWidgets.QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        self.add_button = QtWidgets.QPushButton("Add")
        self.remove_button = QtWidgets.QPushButton("Remove")
        self.up_button = QtWidgets.QPushButton("Up")
        self.down_button = QtWidgets.QPushButton("Down")
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.to_tileset_button = QtWidgets.QPushButton("Add → Tileset")
        self.add_button.setToolTip("Import image files")
        self.remove_button.setToolTip("Remove the selected tile")
        self.up_button.setToolTip("Move the selected tile left (earlier)")
        self.down_button.setToolTip("Move the selected tile right (later)")
        self.clear_button.setToolTip("Remove all tiles")
        self.to_tileset_button.setToolTip(
            "Add the selected (edited / cropped) tile to the Tileset on the right "
            "(toggle to remove it)"
        )
        for b in (self.add_button, self.remove_button, self.up_button,
                  self.down_button, self.clear_button):
            btn_layout.addWidget(b)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.to_tileset_button)

        edit_box = QtWidgets.QGroupBox("Edit Tile")
        edit_box_layout = QtWidgets.QVBoxLayout(edit_box)
        edit_box_layout.setContentsMargins(4, 4, 4, 4)
        edit_hint = QtWidgets.QLabel(
            "Crop: drag inside  ·  Trim a side: drag an edge  ·  Resize: drag a corner  ·  "
            "Diamond select: S  ·  Copy/Paste: Cmd+C / Cmd+V  ·  Right-click: more  ·  "
            "Add → Tileset  ·  Click a preview tile to edit it  ·  Drag in the preview to reorder"
        )
        edit_hint.setWordWrap(True)
        edit_hint.setStyleSheet("color: palette(mid); padding: 2px 2px 4px 2px;")
        self.edit_size_label = QtWidgets.QLabel("No tile selected")
        self.edit_size_label.setStyleSheet("padding: 1px 2px; font-weight: bold;")
        edit_box_layout.addWidget(btn_row)
        edit_box_layout.addWidget(self.tile_list)
        edit_box_layout.addWidget(edit_hint)
        edit_box_layout.addWidget(self._build_tool_row())
        edit_box_layout.addWidget(self.edit_size_label)
        edit_box_layout.addWidget(self.editor_canvas, 1)

        # --- Pane 2: Tileset Preview -------------------------------------
        self.preview_canvas = PreviewCanvas()
        self.preview_canvas.setToolTip(
            "How the exported tileset looks (large tiles span several cells). "
            "Scroll to zoom, drag an empty area to pan, or use the zoom buttons."
        )
        preview_box = QtWidgets.QGroupBox("Tileset Preview")
        preview_box_layout = QtWidgets.QVBoxLayout(preview_box)
        preview_box_layout.setContentsMargins(4, 4, 4, 4)

        # Summary line + zoom controls on one row above the preview.
        preview_top = QtWidgets.QWidget()
        preview_top_layout = QtWidgets.QHBoxLayout(preview_top)
        preview_top_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_summary = QtWidgets.QLabel("Output: empty — add tiles to the tileset")
        self.preview_summary.setStyleSheet("padding: 2px; font-weight: bold;")
        preview_top_layout.addWidget(self.preview_summary, 1)
        self.zoom_out_button = QtWidgets.QToolButton()
        self.zoom_out_button.setText("−")          # minus sign
        self.zoom_out_button.setToolTip("Zoom out (or scroll down on the preview)")
        self.zoom_reset_button = QtWidgets.QToolButton()
        self.zoom_reset_button.setText("Fit")
        self.zoom_reset_button.setToolTip("Fit the whole tileset in view (reset zoom)")
        self.zoom_in_button = QtWidgets.QToolButton()
        self.zoom_in_button.setText("+")
        self.zoom_in_button.setToolTip("Zoom in (or scroll up on the preview)")
        for b in (self.zoom_out_button, self.zoom_reset_button, self.zoom_in_button):
            b.setAutoRaise(True)
            preview_top_layout.addWidget(b)
        preview_box_layout.addWidget(preview_top)
        preview_box_layout.addWidget(self.preview_canvas, 1)

        # --- Pane 3: grid panel (top) + edit panel (scrollable, bottom) --
        right = QtWidgets.QWidget()
        # Give the settings a comfortable minimum width so sliders, value
        # labels (e.g. "1.00"), and buttons are never clipped.
        right.setMinimumWidth(340)
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)

        self.grid_panel = GridPanel(self.model.grid)
        grid_box = QtWidgets.QGroupBox("Grid / Tileset")
        grid_box_layout = QtWidgets.QVBoxLayout(grid_box)
        grid_box_layout.setContentsMargins(4, 4, 4, 4)
        grid_box_layout.addWidget(self.grid_panel)
        right_layout.addWidget(grid_box)

        self.edit_panel = EditPanel()
        edit_scroll = QtWidgets.QScrollArea()
        edit_scroll.setWidgetResizable(True)
        edit_scroll.setWidget(self.edit_panel)
        settings_box = QtWidgets.QGroupBox("Tile Adjustments")
        settings_box_layout = QtWidgets.QVBoxLayout(settings_box)
        settings_box_layout.setContentsMargins(4, 4, 4, 4)
        settings_box_layout.addWidget(edit_scroll)
        right_layout.addWidget(settings_box, 1)

        # --- Assemble the splitter --------------------------------------
        splitter.addWidget(edit_box)
        splitter.addWidget(preview_box)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)  # give the tileset preview more room
        splitter.setStretchFactor(2, 2)

        # A guided 4-step bar sits above the panes so a first-time user always
        # sees the overall flow (Import -> Edit -> Add to Tileset -> Export).
        central = QtWidgets.QWidget()
        central_layout = QtWidgets.QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._build_step_bar())
        central_layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

    def _build_step_bar(self) -> QtWidgets.QWidget:
        """Build the guided 4-step bar shown above the working area.

        Each step is a clickable shortcut to that part of the flow; the step the
        user should do next is highlighted by :meth:`_update_steps`.
        """
        bar = QtWidgets.QFrame()
        bar.setObjectName("stepBar")
        bar.setStyleSheet(
            "#stepBar { background: palette(window); "
            "border-bottom: 1px solid palette(mid); }"
        )
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(4)

        specs = [
            ("①  Import images", "Import image files to start (step 1)",
             lambda: self.import_images()),
            ("②  Edit tile", "Select a tile and edit it on the left (step 2)",
             self._goto_edit_step),
            ("③  Add to Tileset", "Add the selected tile to the output tileset (step 3)",
             lambda: self._set_in_tileset(True)),
            ("④  Export", "Export the packed tileset PNG + .tsx/.tsj (step 4)",
             lambda: self.export_tileset()),
        ]
        self._step_buttons: List[QtWidgets.QToolButton] = []
        for i, (text, tip, handler) in enumerate(specs):
            if i > 0:
                arrow = QtWidgets.QLabel("→")
                arrow.setStyleSheet("color: palette(mid);")
                lay.addWidget(arrow)
            btn = QtWidgets.QToolButton()
            btn.setText(text)
            btn.setToolTip(tip)
            btn.setAutoRaise(True)
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            self._step_buttons.append(btn)
            lay.addWidget(btn)
        lay.addStretch(1)
        return bar

    def _goto_edit_step(self) -> None:
        """Step 2 shortcut: select the first tile (if any) and focus the editor."""
        if not self.model.tiles:
            self.statusBar().showMessage("Import images first (step 1)")
            return
        if self.tile_list.currentRow() < 0:
            self.tile_list.setCurrentRow(0)
        self.editor_canvas.setFocus()

    def _update_steps(self) -> None:
        """Highlight the step the user should do next based on the model state."""
        if not hasattr(self, "_step_buttons"):
            return
        n_tiles = len(self.model.tiles)
        n_tileset = len(self.model.tileset_tiles())
        if n_tiles == 0:
            active = 0           # import
        elif n_tileset == 0:
            active = 2           # add to tileset (editing is optional)
        else:
            active = 3           # export
        for i, btn in enumerate(self._step_buttons):
            if i == active:
                btn.setStyleSheet("QToolButton { font-weight: bold; color: #ff7a00; }")
            else:
                btn.setStyleSheet("QToolButton { color: palette(text); }")

    def _build_tool_row(self) -> QtWidgets.QWidget:
        """Build the editing toolbar above the canvas: one click per tool.

        Every button maps to an existing action so the gestures/shortcuts are
        no longer the only way to edit. Toggle tools (diamond/flip/bg/trim/
        grayscale) are checkable and reflect the selected tile's state.
        """
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tool_diamond = QtWidgets.QPushButton("◇ Diamond")
        self.tool_rotl = QtWidgets.QPushButton("↺ 90°")
        self.tool_rotr = QtWidgets.QPushButton("↻ 90°")
        self.tool_fliph = QtWidgets.QPushButton("⇆ Flip H")
        self.tool_flipv = QtWidgets.QPushButton("⇅ Flip V")
        self.tool_rmbg = QtWidgets.QPushButton("Remove BG")
        self.tool_trim = QtWidgets.QPushButton("Trim")
        self.tool_gray = QtWidgets.QPushButton("Grayscale")
        self.tool_reset = QtWidgets.QPushButton("Reset")
        self.tool_diamond.setToolTip("Diamond select to the tile ratio (S)")
        self.tool_rotl.setToolTip("Rotate 90° counter-clockwise")
        self.tool_rotr.setToolTip("Rotate 90° clockwise")
        for b in (self.tool_diamond, self.tool_fliph, self.tool_flipv,
                  self.tool_rmbg, self.tool_trim, self.tool_gray):
            b.setCheckable(True)
        #: All toolbar buttons (for enable/disable on selection).
        self._tool_buttons = [
            self.tool_diamond, self.tool_rotl, self.tool_rotr, self.tool_fliph,
            self.tool_flipv, self.tool_rmbg, self.tool_trim, self.tool_gray,
            self.tool_reset,
        ]
        for b in self._tool_buttons:
            lay.addWidget(b)
        lay.addStretch(1)
        return row

    def _build_actions(self) -> None:
        """Create the menu bar, toolbar, and status bar."""
        # Workspace save / open (the editable project state, not the packed sheet).
        self.save_workspace_action = QtGui.QAction("Save Workspace...", self)
        self.save_workspace_action.setToolTip(
            "Save the project (tiles + edits + grid) to a .json workspace"
        )
        self.save_workspace_action.setStatusTip("Save the current workspace")
        self.save_workspace_action.setShortcut(QtGui.QKeySequence.StandardKey.Save)
        self.open_workspace_action = QtGui.QAction("Open Workspace...", self)
        self.open_workspace_action.setToolTip("Open a previously saved .json workspace")
        self.open_workspace_action.setStatusTip("Open a saved workspace")
        self.open_workspace_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+O"))

        # Import loose images / export the packed tileset.
        self.import_action = QtGui.QAction("Import Images...", self)
        self.import_action.setToolTip(
            "Import image files into the project (each becomes a tile)"
        )
        self.import_action.setStatusTip("Import one or more images as tiles")
        self.import_action.setShortcut(QtGui.QKeySequence.StandardKey.Open)
        self.import_folder_action = QtGui.QAction("Import Folder...", self)
        self.import_folder_action.setToolTip(
            "Import every image in a folder (and its sub-folders) as tiles"
        )
        self.import_folder_action.setStatusTip("Import all images from a folder")
        self.import_folder_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+I"))
        self.export_action = QtGui.QAction("Export Tileset...", self)
        self.export_action.setToolTip(
            "Export the packed tileset PNG plus its Tiled .tsx/.tsj definition"
        )
        self.export_action.setStatusTip("Export the packed tileset and definitions")
        self.export_action.setShortcut(QtGui.QKeySequence("Ctrl+E"))

        # Undo / redo (Ctrl+Z / Ctrl+Shift+Z, the standard redo).
        self.undo_action = QtGui.QAction("Undo", self)
        self.undo_action.setStatusTip("Undo the last change")
        self.undo_action.setShortcut(QtGui.QKeySequence.StandardKey.Undo)
        self.redo_action = QtGui.QAction("Redo", self)
        self.redo_action.setStatusTip("Redo the last undone change")
        self.redo_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+Z"))

        # .tsx / .tsj toggles (both default to .tsx on, as specified).
        self.tsx_action = QtGui.QAction("Export .tsx", self)
        self.tsx_action.setCheckable(True)
        self.tsx_action.setChecked(True)
        self.tsx_action.setToolTip("Write a Tiled .tsx definition on export")
        self.tsj_action = QtGui.QAction("Export .tsj", self)
        self.tsj_action.setCheckable(True)
        self.tsj_action.setChecked(False)
        self.tsj_action.setToolTip("Write a Tiled .tsj definition on export")

        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.open_workspace_action)
        file_menu.addAction(self.save_workspace_action)
        file_menu.addSeparator()
        file_menu.addAction(self.import_action)
        file_menu.addAction(self.import_folder_action)
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(self.tsx_action)
        file_menu.addAction(self.tsj_action)

        edit_menu = self.menuBar().addMenu("Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction("Copy Tile (Cmd/Ctrl+C)", self._on_copy_tile)
        edit_menu.addAction("Paste to Tileset (Cmd/Ctrl+V)", self._on_paste_tile)
        edit_menu.addSeparator()
        edit_menu.addAction("Delete Tile", self._on_remove)
        edit_menu.addAction("Clear All Tiles", self._on_clear)

        # Tile menu: per-tile edits (same actions as the right-click menu).
        tile_menu = self.menuBar().addMenu("Tile")
        tile_menu.addAction("Diamond Select (S)", self._on_diamond)
        tile_menu.addAction("Remove Background", lambda: self._toggle_edit("bg_remove"))
        tile_menu.addAction("Trim Transparent Border", lambda: self._toggle_edit("trim"))
        tile_menu.addAction("Grayscale", lambda: self._toggle_edit("grayscale"))
        tile_menu.addAction("Flip Horizontal", lambda: self._toggle_edit("flip_h"))
        tile_menu.addAction("Flip Vertical", lambda: self._toggle_edit("flip_v"))
        tile_menu.addSeparator()
        tile_menu.addAction("Reset Tile Edits", self._on_reset_edits)

        # Tileset menu: which tiles go into the output, and their order.
        tileset_menu = self.menuBar().addMenu("Tileset")
        tileset_menu.addAction("Add Selected to Tileset", lambda: self._set_in_tileset(True))
        tileset_menu.addAction("Remove Selected from Tileset", lambda: self._set_in_tileset(False))
        tileset_menu.addSeparator()
        tileset_menu.addAction("Add All to Tileset", self._on_add_all)
        tileset_menu.addAction("Remove All from Tileset", self._on_remove_all)
        tileset_menu.addSeparator()
        tileset_menu.addAction("Move Tile Left", lambda: self._on_move(-1))
        tileset_menu.addAction("Move Tile Right", lambda: self._on_move(1))
        tileset_menu.addSeparator()
        # Clean up: one-click removal of duplicate / empty tiles + sorting.
        cleanup_menu = tileset_menu.addMenu("Clean Up")
        cleanup_menu.addAction("Remove Duplicate Tiles", self._on_dedup)
        cleanup_menu.addAction("Drop Empty (Transparent) Tiles", self._on_drop_empty)
        sort_menu = tileset_menu.addMenu("Sort Tiles By")
        sort_menu.addAction("Original Order", lambda: self._on_sort("none"))
        sort_menu.addAction("Name", lambda: self._on_sort("name"))
        sort_menu.addAction("Natural Name (tile2 < tile10)", lambda: self._on_sort("natural"))

        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction("Keyboard Shortcuts", self._show_shortcuts)

        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        # Show prominent, text-labelled primary buttons (no icons available).
        toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        toolbar.setStyleSheet(
            "QToolButton { font-weight: bold; padding: 6px 14px; }"
        )
        toolbar.addAction(self.import_action)
        toolbar.addAction(self.export_action)
        toolbar.addSeparator()
        toolbar.addAction(self.save_workspace_action)

        self.setStatusBar(QtWidgets.QStatusBar())

    def _connect_signals(self) -> None:
        """Wire up child widget signals to keep the model and views in sync."""
        # Tile list management.
        self.tile_list.currentRowChanged.connect(self._on_row_changed)
        self.add_button.clicked.connect(lambda: self.import_images())
        self.remove_button.clicked.connect(self._on_remove)
        self.up_button.clicked.connect(lambda: self._on_move(-1))
        self.down_button.clicked.connect(lambda: self._on_move(1))
        self.clear_button.clicked.connect(self._on_clear)
        self.to_tileset_button.clicked.connect(self._on_toggle_tileset)
        self.tile_list.customContextMenuRequested.connect(self._on_list_context_menu)

        # Panels.
        self.edit_panel.changed.connect(self._on_edit_changed)
        self.grid_panel.changed.connect(self._on_grid_changed)

        # Editor drag/key gestures: crop, corner-handle resize, diamond mask.
        self.editor_canvas.crop_selected.connect(self._on_crop_selected)
        self.editor_canvas.resize_requested.connect(self._on_resize_requested)
        self.editor_canvas.diamond_requested.connect(self._on_diamond)
        self.editor_canvas.copy_requested.connect(self._on_copy_tile)
        self.editor_canvas.paste_requested.connect(self._on_paste_tile)
        self.editor_canvas.customContextMenuRequested.connect(self._on_editor_context_menu)
        self.preview_canvas.tile_moved.connect(self._on_preview_move)
        self.preview_canvas.tile_clicked.connect(self._on_preview_clicked)
        self.preview_canvas.align_requested.connect(self._on_preview_align)
        self.zoom_in_button.clicked.connect(self.preview_canvas.zoom_in)
        self.zoom_out_button.clicked.connect(self.preview_canvas.zoom_out)
        self.zoom_reset_button.clicked.connect(self.preview_canvas.reset_view)

        # Editing toolbar buttons (above the canvas).
        self.tool_diamond.clicked.connect(self._on_diamond)
        self.tool_rotl.clicked.connect(lambda: self._rotate(90))
        self.tool_rotr.clicked.connect(lambda: self._rotate(-90))
        self.tool_fliph.clicked.connect(lambda: self._toggle_edit("flip_h"))
        self.tool_flipv.clicked.connect(lambda: self._toggle_edit("flip_v"))
        self.tool_rmbg.clicked.connect(lambda: self._toggle_edit("bg_remove"))
        self.tool_trim.clicked.connect(lambda: self._toggle_edit("trim"))
        self.tool_gray.clicked.connect(lambda: self._toggle_edit("grayscale"))
        self.tool_reset.clicked.connect(self._on_reset_edits)

        # Menu / toolbar actions.
        self.import_action.triggered.connect(lambda: self.import_images())
        self.import_folder_action.triggered.connect(lambda: self.import_folder())
        self.export_action.triggered.connect(lambda: self.export_tileset())
        self.save_workspace_action.triggered.connect(lambda: self.save_workspace())
        self.open_workspace_action.triggered.connect(lambda: self.open_workspace())
        self.undo_action.triggered.connect(self._on_undo)
        self.redo_action.triggered.connect(self._on_redo)

    # -- Helpers --------------------------------------------------------
    def _current_tile(self) -> Optional[TileItem]:
        """Return the tile for the current list row, or ``None`` if none selected."""
        row = self.tile_list.currentRow()
        if 0 <= row < len(self.model.tiles):
            return self.model.tiles[row]
        return None

    def _make_icon(self, tile: TileItem) -> QtGui.QIcon:
        """Build a list icon from the tile's rendered thumbnail."""
        return QtGui.QIcon(
            qtutil.pil_to_qpixmap(tile.thumbnail(_ICON_SIZE, self.model.grid))
        )

    def _style_list_item(self, item: "QtWidgets.QListWidgetItem", tile: TileItem) -> None:
        """Apply the thumbnail, label, and 'in tileset' highlight to a list item.

        Tiles included in the tileset get a check-mark prefix and a green
        background so it is obvious which tiles will be exported.
        """
        item.setIcon(self._make_icon(tile))
        name = os.path.basename(tile.path)
        if tile.in_tileset:
            item.setText("✓ " + name)
            item.setBackground(QtGui.QColor(38, 84, 46))
            item.setToolTip("In the tileset. Click 'Remove from Tileset' to exclude it.")
        else:
            item.setText(name)
            item.setBackground(QtGui.QBrush())
            item.setToolTip("Source only — click 'Add → Tileset' to include it in the output.")

    def _append_list_item(self, tile: TileItem) -> None:
        """Append a list widget item (thumbnail + label + tileset highlight)."""
        item = QtWidgets.QListWidgetItem()
        self.tile_list.addItem(item)
        self._style_list_item(item, tile)

    def _rebuild_list(self, select_row: Optional[int] = None) -> None:
        """Rebuild the whole list from the model, optionally re-selecting a row."""
        blocker = QtCore.QSignalBlocker(self.tile_list)
        self.tile_list.clear()
        for tile in self.model.tiles:
            self._append_list_item(tile)
        del blocker
        if self.model.tiles:
            row = 0 if select_row is None else max(0, min(select_row, len(self.model.tiles) - 1))
            self.tile_list.setCurrentRow(row)
        else:
            self._sync_selection(None)

    def _refresh_current_icon(self) -> None:
        """Re-render the current list item (icon + label + tileset highlight)."""
        row = self.tile_list.currentRow()
        tile = self._current_tile()
        if tile is None:
            return
        item = self.tile_list.item(row)
        if item is not None:
            self._style_list_item(item, tile)

    def _update_tileset_button(self, tile: Optional[TileItem]) -> None:
        """Make the Add/Remove Tileset button reflect the selected tile's state."""
        if tile is None:
            self.to_tileset_button.setEnabled(False)
            self.to_tileset_button.setText("Add → Tileset")
        else:
            self.to_tileset_button.setEnabled(True)
            self.to_tileset_button.setText(
                "Remove from Tileset" if tile.in_tileset else "Add → Tileset"
            )

    def _show_in_editor(self, tile: TileItem) -> None:
        """Update the edit canvas with the tile's un-masked image + diamond outline.

        The editor always shows the image WITHOUT the diamond mask applied, plus a
        diamond *selection* outline when ``edit.diamond`` is on; the mask itself is
        applied only in the tileset preview and the export.
        """
        grid = self.model.grid
        self.editor_canvas.set_cell_size(grid.tile_width, grid.tile_height)
        self.editor_canvas.set_image(tile.display_image(grid, apply_diamond=False))
        self.editor_canvas.set_diamond_overlay(tile.edit.diamond)
        # Crop can only be mapped to a source crop when the rendered image is an
        # axis-aligned view of the source; rotation/trim break that, so disable
        # crop gestures (resize stays available) and avoid corrupting the tile.
        crop_ok = (tile.edit.rotation % 360 == 0) and not tile.edit.trim
        self.editor_canvas.set_crop_enabled(crop_ok)
        sw, sh = tile.source.size
        dw, dh = tile.display_size(grid)
        sc, sr = tile.cell_span(grid)
        self.edit_size_label.setText(
            f"Source {sw}×{sh}px  ·  Current {dw}×{dh}px  ·  spans {sc}×{sr} cell(s)"
        )

    def _sync_selection(self, tile: Optional[TileItem]) -> None:
        """Push the selected tile into the edit panel and editor canvas.

        The editor shows the tile at its *display size* (edits + ``edit.scale``)
        so resizing with the corner handles is reflected immediately. If the
        tile is part of the tileset, its cell is also highlighted in the preview.
        """
        self.edit_panel.set_tile(tile)
        self._update_tileset_button(tile)
        self._sync_tools(tile)
        self._sync_preview_selection(tile)
        if tile is None:
            self.editor_canvas.clear()
            self.editor_canvas.set_diamond_overlay(False)
            self.edit_size_label.setText("No tile selected")
            return
        self._show_in_editor(tile)

    def _sync_preview_selection(self, tile: Optional[TileItem]) -> None:
        """Highlight ``tile`` in the preview when it is part of the tileset."""
        idx: Optional[int] = None
        if tile is not None and tile.in_tileset:
            try:
                idx = self.model.tileset_tiles().index(tile)
            except ValueError:
                idx = None
        self.preview_canvas.set_selected(idx)

    def _on_preview_clicked(self, ts_index: int) -> None:
        """Select the clicked preview tile in the Edit Tile list/canvas.

        ``ts_index`` is an index into the tileset tiles; it is mapped back to the
        underlying source row so the existing selection machinery takes over.
        """
        ts = self.model.tileset_tiles()
        if not (0 <= ts_index < len(ts)):
            return
        tile = ts[ts_index]
        try:
            row = self.model.tiles.index(tile)
        except ValueError:
            return
        # Setting the current row fires _on_row_changed -> _sync_selection, which
        # updates the editor, panels, and the preview highlight.
        self.tile_list.setCurrentRow(row)

    # -- Slots ----------------------------------------------------------
    def _on_row_changed(self, row: int) -> None:
        """Handle a list selection change by syncing the dependent views."""
        self._sync_selection(self._current_tile())

    def _on_remove(self) -> None:
        """Remove the selected tile and refresh the dependent views."""
        row = self.tile_list.currentRow()
        if not (0 <= row < len(self.model.tiles)):
            return
        self.model.remove(row)
        self.model.commit()
        self._rebuild_list(select_row=row)
        self._refresh_preview()
        self.statusBar().showMessage("Removed tile")

    def _on_move(self, delta: int) -> None:
        """Move the selected tile by ``delta`` positions and refresh views."""
        row = self.tile_list.currentRow()
        if not (0 <= row < len(self.model.tiles)):
            return
        new_row = self.model.move(row, delta)
        self.model.commit()
        self._rebuild_list(select_row=new_row)
        self._refresh_preview()

    def _on_clear(self) -> None:
        """Remove all tiles and refresh the dependent views."""
        if not self.model.tiles:
            return
        self.model.clear()
        self.model.commit()
        self._rebuild_list()
        self._refresh_preview()
        self.statusBar().showMessage("Cleared all tiles")

    def _on_toggle_tileset(self) -> None:
        """Toggle whether the selected tile is included in the tileset."""
        tile = self._current_tile()
        if tile is None:
            return
        tile.in_tileset = not tile.in_tileset
        self.model.commit()
        self._refresh_current_icon()
        self._update_tileset_button(tile)
        self._refresh_preview()
        n = len(self.model.tileset_tiles())
        state = "added to" if tile.in_tileset else "removed from"
        self.statusBar().showMessage(f"Tile {state} the tileset ({n} in tileset)")

    # -- Editing toolbar ------------------------------------------------
    def _rotate(self, degrees: float) -> None:
        """Rotate the current tile by ``degrees`` (toolbar 90° buttons)."""
        tile = self._current_tile()
        if tile is None:
            return
        tile.edit.rotation = (tile.edit.rotation + degrees) % 360
        self._apply_quick_edit(tile)

    def _sync_tools(self, tile: Optional[TileItem]) -> None:
        """Enable the toolbar and reflect the selected tile's toggle states."""
        for b in self._tool_buttons:
            b.setEnabled(tile is not None)
        if tile is None:
            return
        for button, value in (
            (self.tool_diamond, tile.edit.diamond),
            (self.tool_fliph, tile.edit.flip_h),
            (self.tool_flipv, tile.edit.flip_v),
            (self.tool_rmbg, tile.edit.bg_remove),
            (self.tool_trim, tile.edit.trim),
            (self.tool_gray, tile.edit.grayscale),
        ):
            button.setChecked(value)

    # -- Menu helpers ---------------------------------------------------
    def _toggle_edit(self, attr: str) -> None:
        """Toggle a boolean edit field of the current tile (menu actions)."""
        tile = self._current_tile()
        if tile is None:
            return
        setattr(tile.edit, attr, not getattr(tile.edit, attr))
        self._apply_quick_edit(tile)

    def _on_reset_edits(self) -> None:
        """Reset all edits of the current tile."""
        tile = self._current_tile()
        if tile is None:
            return
        tile.edit.reset()
        self._apply_quick_edit(tile)

    def _set_in_tileset(self, value: bool) -> None:
        """Set the current tile's tileset membership to ``value``."""
        tile = self._current_tile()
        if tile is None or tile.in_tileset == value:
            return
        self._on_toggle_tileset()

    def _on_add_all(self) -> None:
        """Add every source tile to the tileset."""
        if not self.model.tiles:
            return
        for t in self.model.tiles:
            t.in_tileset = True
        self.model.commit()
        self._rebuild_list()
        self._refresh_preview()
        self.statusBar().showMessage(
            f"Added all tiles to the tileset ({len(self.model.tileset_tiles())})"
        )

    def _on_remove_all(self) -> None:
        """Remove every tile from the tileset (they remain as sources)."""
        for t in self.model.tiles:
            t.in_tileset = False
        self.model.commit()
        self._rebuild_list()
        self._refresh_preview()
        self.statusBar().showMessage("Removed all tiles from the tileset")

    # -- Clean up / organize --------------------------------------------
    def _on_dedup(self) -> None:
        """Remove tiles that duplicate an earlier tile's rendered pixels."""
        row = self.tile_list.currentRow()
        removed = self.model.deduplicate()
        if removed:
            self.model.commit()
            self._rebuild_list(select_row=row)
            self._refresh_preview()
            self.statusBar().showMessage(f"Removed {removed} duplicate tile(s)")
        else:
            self.statusBar().showMessage("No duplicate tiles found")

    def _on_drop_empty(self) -> None:
        """Remove fully transparent tiles from the project."""
        row = self.tile_list.currentRow()
        removed = self.model.drop_empty()
        if removed:
            self.model.commit()
            self._rebuild_list(select_row=row)
            self._refresh_preview()
            self.statusBar().showMessage(f"Dropped {removed} empty tile(s)")
        else:
            self.statusBar().showMessage("No empty tiles found")

    def _on_sort(self, mode: str) -> None:
        """Sort the tiles by ``mode`` (none / name / natural)."""
        if mode == "none" or not self.model.tiles:
            return
        self.model.sort_tiles(mode)
        self.model.commit()
        self._rebuild_list(select_row=0)
        self._refresh_preview()
        self.statusBar().showMessage(f"Sorted tiles by {mode}")

    def _show_shortcuts(self) -> None:
        """Show a small keyboard shortcut cheat-sheet."""
        QtWidgets.QMessageBox.information(
            self,
            "Keyboard Shortcuts",
            "S\tDiamond select (tile ratio)\n"
            "Cmd/Ctrl+C\tCopy selected tile\n"
            "Cmd/Ctrl+V\tPaste into the tileset\n"
            "Cmd/Ctrl+O\tImport images\n"
            "Cmd/Ctrl+S\tSave workspace\n"
            "Cmd/Ctrl+Z / +R\tUndo / Redo\n\n"
            "Drag inside the canvas: crop  ·  Drag a corner: resize\n"
            "Right-click a tile: more actions  ·  Drag in the preview: reorder",
        )

    # -- Preview refresh + status summary -------------------------------
    def _refresh_preview(self) -> None:
        """Repaint the tileset preview and update its summary, steps and highlight."""
        self.preview_canvas.refresh()
        self._update_preview_summary()
        # Keep the preview highlight pointing at the current selection after any
        # layout change (reorder / add / remove can shift tileset indices).
        self._sync_preview_selection(self._current_tile())
        self._update_steps()

    def _update_preview_summary(self) -> None:
        """Update the output summary above the preview (count / cols / size / defs)."""
        import math

        n = len(self.model.tileset_tiles())
        if n == 0:
            self.preview_summary.setText(
                "Output: empty — select a tile and click “Add → Tileset”"
            )
            return
        g = self.model.grid
        if g.fit_to_cell:
            cols = g.columns if g.columns > 0 else max(1, math.ceil(math.sqrt(n)))
            rows = math.ceil(n / cols)
        else:
            try:
                _, cols, rows = self.model.shelf_layout()
            except Exception:
                cols = rows = 0
        defs = [
            name
            for name, on in (("TSX", self.tsx_action.isChecked()), ("TSJ", self.tsj_action.isChecked()))
            if on
        ]
        defs_text = " + ".join(defs) if defs else "PNG only"
        size = f"{cols * g.tile_width}×{rows * g.tile_height}px" if cols and rows else ""
        parts = [f"Output: {n} tiles", f"{cols} cols" if cols else "", size, defs_text]
        self.preview_summary.setText("  ·  ".join(p for p in parts if p))

    # -- Preview alignment (right-click) --------------------------------
    def _on_preview_align(self, index: int, align: str) -> None:
        """Align a tileset tile within its cell span (preview right-click menu)."""
        ts = self.model.tileset_tiles()
        if not (0 <= index < len(ts)):
            return
        ts[index].edit.align = align
        self.model.commit()
        self._refresh_preview()
        self.statusBar().showMessage(f"Aligned tile to '{align}' within its cell")

    # -- Preview drag-to-reorder ----------------------------------------
    def _on_preview_move(self, from_idx: int, to_idx: int) -> None:
        """Reorder the tileset tiles after a drag in the preview.

        The tileset tiles are reordered while the source-only tiles keep their
        positions in the underlying list.
        """
        ts = self.model.tileset_tiles()
        n = len(ts)
        if from_idx == to_idx or not (0 <= from_idx < n) or not (0 <= to_idx < n):
            return
        moved = ts[from_idx]
        new_order = [t for t in ts if t is not moved]
        new_order.insert(to_idx, moved)
        order_iter = iter(new_order)
        self.model.tiles = [
            next(order_iter) if t.in_tileset else t for t in self.model.tiles
        ]
        self.model.commit()
        self._rebuild_list()
        self._refresh_preview()
        self.statusBar().showMessage("Reordered the tileset")

    # -- Copy / paste (Cmd/Ctrl+C, Cmd/Ctrl+V) --------------------------
    def _on_copy_tile(self) -> None:
        """Copy the selected tile (with its current edits) to an internal clipboard."""
        tile = self._current_tile()
        if tile is None:
            return
        self._copied_tile = tile.clone()
        self.statusBar().showMessage("Copied — press Cmd/Ctrl+V to add it to the tileset")

    def _on_paste_tile(self) -> None:
        """Paste the copied tile into the tileset as a new tile."""
        copied = getattr(self, "_copied_tile", None)
        if copied is None:
            self.statusBar().showMessage("Nothing copied — press Cmd/Ctrl+C on a tile first")
            return
        new = copied.clone()
        new.in_tileset = True
        self.model.tiles.append(new)
        self.model.commit()
        self._rebuild_list(select_row=len(self.model.tiles) - 1)
        self._refresh_preview()
        self.statusBar().showMessage(
            f"Pasted into the tileset ({len(self.model.tileset_tiles())} in tileset)"
        )

    # -- Drag & drop import --------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Accept drags that carry file URLs so images can be dropped in."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Keep accepting the drag while it moves over the window."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Import any image files dropped onto the window."""
        paths = [
            u.toLocalFile()
            for u in event.mimeData().urls()
            if u.isLocalFile() and u.toLocalFile()
        ]
        if paths:
            self.import_images(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    # -- Right-click context menu --------------------------------------
    def _show_tile_context_menu(self, global_pos) -> None:
        """Build and run the per-tile quick-action menu at a global screen position.

        Shared by the tile-list thumbnails and the edit canvas right-click.
        """
        tile = self._current_tile()
        if tile is None:
            return

        menu = QtWidgets.QMenu(self)
        act_toggle = menu.addAction(
            "Remove from Tileset" if tile.in_tileset else "Add to Tileset"
        )
        act_copy = menu.addAction("Copy (Cmd/Ctrl+C)")
        menu.addSeparator()
        act_diamond = menu.addAction("Diamond crop (tile ratio)")
        act_diamond.setCheckable(True)
        act_diamond.setChecked(tile.edit.diamond)
        act_rmbg = menu.addAction("Remove background")
        act_rmbg.setCheckable(True)
        act_rmbg.setChecked(tile.edit.bg_remove)
        act_trim = menu.addAction("Trim transparent border")
        act_trim.setCheckable(True)
        act_trim.setChecked(tile.edit.trim)
        act_gray = menu.addAction("Grayscale")
        act_gray.setCheckable(True)
        act_gray.setChecked(tile.edit.grayscale)
        menu.addSeparator()
        act_fliph = menu.addAction("Flip horizontal")
        act_fliph.setCheckable(True)
        act_fliph.setChecked(tile.edit.flip_h)
        act_flipv = menu.addAction("Flip vertical")
        act_flipv.setCheckable(True)
        act_flipv.setChecked(tile.edit.flip_v)
        act_reset = menu.addAction("Reset all edits")
        menu.addSeparator()
        act_delete = menu.addAction("Delete tile")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen == act_toggle:
            self._on_toggle_tileset()
        elif chosen == act_copy:
            self._on_copy_tile()
        elif chosen == act_diamond:
            tile.edit.diamond = not tile.edit.diamond
            self._apply_quick_edit(tile)
        elif chosen == act_rmbg:
            tile.edit.bg_remove = not tile.edit.bg_remove
            self._apply_quick_edit(tile)
        elif chosen == act_trim:
            tile.edit.trim = not tile.edit.trim
            self._apply_quick_edit(tile)
        elif chosen == act_gray:
            tile.edit.grayscale = not tile.edit.grayscale
            self._apply_quick_edit(tile)
        elif chosen == act_fliph:
            tile.edit.flip_h = not tile.edit.flip_h
            self._apply_quick_edit(tile)
        elif chosen == act_flipv:
            tile.edit.flip_v = not tile.edit.flip_v
            self._apply_quick_edit(tile)
        elif chosen == act_reset:
            tile.edit.reset()
            self._apply_quick_edit(tile)
        elif chosen == act_delete:
            self._on_remove()

    def _on_list_context_menu(self, pos) -> None:
        """Right-click menu on a tile thumbnail in the list."""
        item = self.tile_list.itemAt(pos)
        if item is not None:
            self.tile_list.setCurrentRow(self.tile_list.row(item))
        self._show_tile_context_menu(self.tile_list.mapToGlobal(pos))

    def _on_editor_context_menu(self, pos) -> None:
        """Right-click menu inside the edit canvas (same actions as the list)."""
        self._show_tile_context_menu(self.editor_canvas.mapToGlobal(pos))

    def _apply_quick_edit(self, tile) -> None:
        """Refresh every dependent view after a quick context-menu edit."""
        self.model.commit()
        self._sync_selection(tile)
        self._refresh_current_icon()
        self._refresh_preview()

    def _on_edit_changed(self) -> None:
        """Re-render the current tile after a per-tile edit change.

        The edit panel's ``changed`` covers the size slider too, so the editor
        is refreshed at the tile's display size and the preview re-laid out.
        """
        tile = self._current_tile()
        if tile is None:
            return
        self._show_in_editor(tile)
        self._refresh_current_icon()
        self._refresh_preview()
        # Coalesce a stream of panel edits (e.g. a slider drag) into one undo.
        self.model.commit(coalesce="edit")

    def _on_grid_changed(self) -> None:
        """React to grid setting changes (cell size + preview layout)."""
        grid = self.model.grid
        self.editor_canvas.set_cell_size(grid.tile_width, grid.tile_height)
        # Re-render the current tile too: the grid ratio drives the diamond mask
        # and the cell-size guide.
        tile = self._current_tile()
        if tile is not None:
            self._show_in_editor(tile)
            self._refresh_current_icon()
        self._refresh_preview()
        self.model.commit(coalesce="grid")

    def _on_crop_selected(self, box) -> None:
        """Apply a crop selected on the editor canvas to the current tile.

        The box is in displayed-image pixels, so it is mapped back to source
        coordinates and composed with any existing crop (see
        :meth:`TileItem.compose_crop_from_display`). This makes repeated crops
        accumulate instead of overwriting against the original source — without
        it, cropping an already-cropped tile would drop its content.
        """
        tile = self._current_tile()
        if tile is None:
            return
        display_w, display_h = self.editor_canvas.image_size()
        new_crop = tile.compose_crop_from_display(tuple(box), display_w, display_h)
        if new_crop is None:
            # Rotation / trim make an axis-aligned source crop ambiguous; refuse
            # rather than corrupt the tile.
            self.statusBar().showMessage(
                "Crop is unavailable while Rotation or Trim is applied — "
                "reset them first, or crop before rotating/trimming."
            )
            return
        tile.edit.crop = new_crop
        # Keep showing the tile at its display size after cropping.
        self._show_in_editor(tile)
        self._refresh_current_icon()
        self._refresh_preview()
        # Re-sync the edit panel so any crop-dependent state stays consistent.
        self.edit_panel.set_tile(tile)
        self.model.commit()
        self.statusBar().showMessage(f"Cropped to {new_crop}")

    def _on_resize_requested(self, factor: float) -> None:
        """Apply a corner-handle drag resize to the current tile's display size.

        The dragged factor (relative to the current display size) is multiplied
        into ``edit.scale`` with a small lower bound so the tile can never
        collapse, then every dependent view is refreshed.
        """
        tile = self._current_tile()
        if tile is None:
            return
        # Clamp to the same 0.1..4.0 range as the EditPanel size slider so the
        # drag handles and the slider stay consistent and a tile can never grow
        # to a runaway pixel size.
        tile.edit.scale = max(0.1, min(4.0, tile.edit.scale * float(factor)))
        self._show_in_editor(tile)
        self._refresh_preview()
        # Re-sync the edit panel so its size slider/label match the new scale.
        self.edit_panel.set_tile(tile)
        self._refresh_current_icon()
        self.model.commit()
        self.statusBar().showMessage(
            f"Resized to {round(tile.edit.scale * 100)}%"
        )

    # -- Public API -----------------------------------------------------
    def import_images(self, paths: Optional[List[str]] = None, *, notify: bool = True) -> int:
        """Import images into the project.

        Args:
            paths: Explicit list of file paths. When ``None``, a file-open
                dialog is shown (multi-select).
            notify: When True, show a modal dialog for load failures. Pass False
                for headless/automated use to avoid blocking modal dialogs.

        Returns:
            The number of tiles actually added.
        """
        if paths is None:
            paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
                self, "Import Images", "", _IMAGE_FILTER
            )
        if not paths:
            return 0
        added, failed = self.model.add_paths(paths)
        if added:
            self.model.commit()
            # Select the first newly imported tile and refresh the preview so it
            # is visible right away. Edit and Preview are shown side by side, so
            # there is no tab to switch to.
            self._rebuild_list(select_row=len(self.model.tiles) - added)
            self._refresh_preview()
        if failed and notify:
            QtWidgets.QMessageBox.warning(
                self,
                "Import",
                "Could not load:\n" + "\n".join(os.path.basename(p) for p in failed),
            )
        self.statusBar().showMessage(
            f"Imported {added} tile(s)"
            + (f", {len(failed)} failed" if failed else "")
        )
        return added

    def import_folder(
        self, folder: Optional[str] = None, *, recursive: bool = True, notify: bool = True
    ) -> int:
        """Import every supported image in a folder (optionally recursively).

        Args:
            folder: Directory to scan. When ``None``, a folder-picker is shown.
            recursive: When True, also scan sub-folders.
            notify: When True, show a modal dialog for load failures.

        Returns:
            The number of tiles actually added.
        """
        if folder is None:
            folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Import Folder")
        if not folder:
            return 0
        exts = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
        paths: List[str] = []
        if recursive:
            for root, _dirs, files in os.walk(folder):
                for f in sorted(files):
                    if os.path.splitext(f)[1].lower() in exts:
                        paths.append(os.path.join(root, f))
        else:
            for f in sorted(os.listdir(folder)):
                p = os.path.join(folder, f)
                if os.path.isfile(p) and os.path.splitext(f)[1].lower() in exts:
                    paths.append(p)
        if not paths:
            self.statusBar().showMessage("No images found in the selected folder")
            return 0
        return self.import_images(paths, notify=notify)

    def export_tileset(
        self,
        path: Optional[str] = None,
        *,
        write_tsx: Optional[bool] = None,
        write_tsj: Optional[bool] = None,
        notify: bool = True,
    ):
        """Export the project as a packed tileset (PNG + .tsx/.tsj).

        Args:
            path: Output PNG path. When ``None``, a save dialog is shown.
            write_tsx: Override the .tsx toggle (defaults to the menu state).
            write_tsj: Override the .tsj toggle (defaults to the menu state).
            notify: When True, show modal success/failure dialogs. Pass False
                for headless/automated use to avoid blocking modal dialogs.

        Returns:
            The core ``ExportResult`` on success, or ``None`` on failure / cancel.
        """
        if not self.model.tileset_tiles():
            if notify:
                QtWidgets.QMessageBox.information(
                    self,
                    "Export",
                    "The tileset is empty.\n\nSelect a tile on the left and click "
                    "'Add → Tileset' to add it to the output, then export.",
                )
            return None

        if path is None:
            default = (self.model.grid.name or "tileset") + ".png"
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Export Tileset", default, "PNG image (*.png)"
            )
        if not path:
            return None

        if write_tsx is None:
            write_tsx = self.tsx_action.isChecked()
        if write_tsj is None:
            write_tsj = self.tsj_action.isChecked()

        try:
            result = self.model.export(
                path, write_tsx=write_tsx, write_tsj=write_tsj
            )
        except Exception as exc:  # pragma: no cover - surfaced to the user
            if notify:
                QtWidgets.QMessageBox.critical(
                    self, "Export failed", f"Could not export the tileset:\n{exc}"
                )
            self.statusBar().showMessage("Export failed")
            return None

        extras = []
        if result.tsx_path:
            extras.append(os.path.basename(result.tsx_path))
        if result.tsj_path:
            extras.append(os.path.basename(result.tsj_path))
        suffix = (" + " + ", ".join(extras)) if extras else ""
        message = (
            f"Exported {result.tile_count} tile(s) "
            f"({result.columns}x{result.rows}) to "
            f"{os.path.basename(result.image_path)}{suffix}"
        )
        if notify:
            QtWidgets.QMessageBox.information(self, "Export", message)
        self.statusBar().showMessage(message)
        return result

    def save_workspace(self, path: Optional[str] = None, *, notify: bool = True) -> Optional[str]:
        """Save the project to a JSON workspace file.

        Args:
            path: Output ``.json`` path. When ``None``, a save dialog is shown.
            notify: When True, show a modal dialog on failure. Pass False for
                headless/automated use.

        Returns:
            The path written on success, or ``None`` on failure / cancel.
        """
        if path is None:
            default = (self.model.grid.name or "workspace") + ".json"
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Save Workspace", default, _WORKSPACE_FILTER
            )
        if not path:
            return None
        try:
            saved = self.model.save_workspace(path)
        except Exception as exc:  # pragma: no cover - surfaced to the user
            if notify:
                QtWidgets.QMessageBox.critical(
                    self, "Save failed", f"Could not save the workspace:\n{exc}"
                )
            self.statusBar().showMessage("Save failed")
            return None
        self.statusBar().showMessage(f"Saved workspace to {os.path.basename(saved)}")
        return saved

    def open_workspace(self, path: Optional[str] = None, *, notify: bool = True) -> bool:
        """Open a JSON workspace file, replacing the current project.

        Args:
            path: Workspace ``.json`` path. When ``None``, an open dialog is shown.
            notify: When True, show a modal dialog for missing tiles / failure.
                Pass False for headless/automated use.

        Returns:
            True if a workspace was loaded, False on failure / cancel.
        """
        if path is None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Open Workspace", "", _WORKSPACE_FILTER
            )
        if not path:
            return False
        try:
            loaded, failed = self.model.load_workspace(path)
        except Exception as exc:  # pragma: no cover - surfaced to the user
            if notify:
                QtWidgets.QMessageBox.critical(
                    self, "Open failed", f"Could not open the workspace:\n{exc}"
                )
            self.statusBar().showMessage("Open failed")
            return False
        # The model replaced its grid object, so re-bind the grid panel to it.
        self.grid_panel.bind(self.model.grid)
        self._rebuild_list(select_row=0)
        self._refresh_preview()
        if failed and notify:
            QtWidgets.QMessageBox.warning(
                self,
                "Open Workspace",
                "Could not load:\n" + "\n".join(os.path.basename(p) for p in failed),
            )
        self.statusBar().showMessage(
            f"Loaded {loaded} tile(s)" + (f", {len(failed)} missing" if failed else "")
        )
        return True

    # -- Undo / redo ----------------------------------------------------
    def _on_undo(self) -> None:
        """Undo the last change and reload every view from the model."""
        if not self.model.undo():
            self.statusBar().showMessage("Nothing to undo")
            return
        self._reload_views()
        self.statusBar().showMessage("Undo")

    def _on_redo(self) -> None:
        """Redo the last undone change and reload every view from the model."""
        if not self.model.redo():
            self.statusBar().showMessage("Nothing to redo")
            return
        self._reload_views()
        self.statusBar().showMessage("Redo")

    def _reload_views(self) -> None:
        """Rebuild all views after a wholesale model state change (undo/redo).

        Undo/redo replace ``model.tiles`` and ``model.grid`` with fresh objects,
        so the grid panel is re-bound and the tile list is rebuilt (which re-syncs
        the editor and edit panel via the selection change).
        """
        row = self.tile_list.currentRow()
        self.grid_panel.bind(self.model.grid)
        self._rebuild_list(select_row=row)
        self._refresh_preview()

    def _on_diamond(self) -> None:
        """Toggle the tile-ratio diamond select (S key).

        The mask is applied in the tileset preview/export; the editor shows the
        un-masked image with a diamond selection outline.
        """
        tile = self._current_tile()
        if tile is None:
            return
        tile.edit.diamond = not tile.edit.diamond
        self.model.commit()
        self._show_in_editor(tile)
        self._sync_tools(tile)
        self._refresh_current_icon()
        self._refresh_preview()
        state = "on" if tile.edit.diamond else "off"
        self.statusBar().showMessage(
            f"Diamond select {state} — applied in the tileset, shown as an outline here"
        )
