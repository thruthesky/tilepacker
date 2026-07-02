"""Right-hand settings panels for the tilepacker GUI.

Two reusable widgets:

* :class:`GridPanel` edits the shared :class:`~tilepacker.gui_app.model.GridSettings`
  (orientation, cell size, columns/margin/spacing/extrude, resize mode, name,
  background color).
* :class:`EditPanel` edits the per-tile :class:`~tilepacker.gui_app.model.TileEdit`
  of the currently selected tile (rotation, flip, color adjustments, background
  removal, trim, resize-mode override, crop reset).

Both panels mutate the bound model object in place and emit a ``changed`` signal
*after* the model has been updated, so a parent window can re-render in response.
Programmatic synchronization is guarded by an ``_updating`` flag so that pushing
values into the widgets never re-emits ``changed`` recursively.

These widgets are constructible headless (offscreen): the constructor only builds
widgets and wires signals; it never shows a window or assumes a running event
loop. All user-facing text is in English (project SSOT).
"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from tilepacker.core.config import RESIZE_MODES, RGBA, parse_color
from tilepacker.gui_app.model import ORIENTATIONS, GridSettings, TileItem

__all__ = ["GridPanel", "EditPanel"]

#: Label used for the "inherit the grid's resize mode" choice.
_GRID_DEFAULT = "(grid default)"

#: Selectable cell sizes offered by the grid panel dropdowns.
_TILE_WIDTH_CHOICES = (32, 64, 128, 256)
_TILE_HEIGHT_CHOICES = (16, 32, 64, 128)


def _set_size_combo(combo: QtWidgets.QComboBox, value: int) -> None:
    """Select ``value`` in a size dropdown, inserting it if not already listed."""
    text = str(int(value))
    idx = combo.findText(text)
    if idx < 0:
        # Allow values set programmatically (e.g. via the API) that are not in
        # the preset list by adding them as a sorted extra option.
        combo.addItem(text)
        idx = combo.findText(text)
    combo.setCurrentIndex(max(0, idx))


def _rgba_to_qcolor(color: Optional[RGBA]) -> QtGui.QColor:
    """Convert an RGBA tuple (or ``None``) to a ``QColor`` for the color dialog."""
    if color is None:
        return QtGui.QColor(0, 0, 0, 255)
    r, g, b, a = color
    return QtGui.QColor(int(r), int(g), int(b), int(a))


def _qcolor_to_rgba(color: QtGui.QColor) -> RGBA:
    """Convert a ``QColor`` to an RGBA 4-tuple."""
    return (color.red(), color.green(), color.blue(), color.alpha())


def _style_color_button(button: QtWidgets.QPushButton, color: Optional[RGBA], *, none_text: str) -> None:
    """Paint a swatch on a color button, or show ``none_text`` when unset."""
    if color is None:
        button.setStyleSheet("")
        button.setText(none_text)
        return
    r, g, b, a = color
    # Choose a readable text color against the swatch.
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    fg = "#000000" if luminance > 140 else "#ffffff"
    button.setStyleSheet(
        f"background-color: rgba({r}, {g}, {b}, {a}); color: {fg};"
    )
    button.setText(f"#{r:02x}{g:02x}{b:02x}")


class GridPanel(QtWidgets.QWidget):
    """Editor for the shared grid/tileset settings.

    The panel holds the bound :class:`GridSettings` object directly and writes
    every change straight into it, emitting :attr:`changed` afterwards.
    """

    #: Emitted after a user edit has been written into the bound grid.
    changed = QtCore.Signal()

    def __init__(self, grid: GridSettings, parent: Optional[QtWidgets.QWidget] = None):
        """Build the panel and bind it to ``grid``.

        Args:
            grid: The :class:`GridSettings` to edit in place.
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self._grid = grid
        self._updating = False

        outer = QtWidgets.QVBoxLayout(self)

        # Basic settings (always visible): orientation, cell size, columns.
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        outer.addLayout(form)

        # Orientation -----------------------------------------------------
        self.orientation = QtWidgets.QComboBox()
        self.orientation.addItems(list(ORIENTATIONS))
        self.orientation.setToolTip("Tile grid orientation")
        form.addRow("Orientation", self.orientation)

        # Cell size (dropdowns) -------------------------------------------
        self.tile_width = QtWidgets.QComboBox()
        self.tile_width.addItems([str(v) for v in _TILE_WIDTH_CHOICES])
        self.tile_width.setToolTip("Cell width in pixels")
        form.addRow("Tile width", self.tile_width)

        self.tile_height = QtWidgets.QComboBox()
        self.tile_height.addItems([str(v) for v in _TILE_HEIGHT_CHOICES])
        self.tile_height.setToolTip("Cell height in pixels")
        form.addRow("Tile height", self.tile_height)

        # Layout ----------------------------------------------------------
        self.columns = QtWidgets.QSpinBox()
        self.columns.setRange(0, 4096)
        self.columns.setToolTip("Number of columns (0 = auto, near-square)")
        form.addRow("Columns", self.columns)

        self.rows = QtWidgets.QSpinBox()
        self.rows.setRange(0, 4096)
        self.rows.setToolTip(
            "Minimum number of rows to show (0 = auto). Set > 0 to show a full "
            "grid of empty slots and place tiles at explicit positions: copy a "
            "cell on the left, then click an empty slot in the preview."
        )
        form.addRow("Rows", self.rows)

        # Advanced section toggle -----------------------------------------
        # Collapsed by default; holds margin/spacing/extrude/resize-mode/name/
        # background and the fit-to-cell mode switch so the panel stays simple.
        self.advanced_toggle = QtWidgets.QToolButton()
        self.advanced_toggle.setText("Advanced: margin, spacing, background, mode")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.advanced_toggle.setArrowType(QtCore.Qt.ArrowType.RightArrow)
        self.advanced_toggle.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.advanced_toggle.setStyleSheet(
            "QToolButton { border: none; font-weight: bold; padding: 4px 0; }"
        )
        self.advanced_toggle.setToolTip(
            "Show margin, spacing, extrude, resize mode, name, background "
            "and the fit-to-cell layout mode"
        )
        outer.addWidget(self.advanced_toggle)

        self.advanced_container = QtWidgets.QWidget()
        advanced_form = QtWidgets.QFormLayout(self.advanced_container)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        advanced_form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        outer.addWidget(self.advanced_container)
        self.advanced_container.setVisible(False)

        self.margin = QtWidgets.QSpinBox()
        self.margin.setRange(0, 4096)
        self.margin.setToolTip("Outer margin around the tileset (px)")
        advanced_form.addRow("Margin", self.margin)

        self.spacing = QtWidgets.QSpinBox()
        self.spacing.setRange(0, 4096)
        self.spacing.setToolTip("Spacing between tiles (px)")
        advanced_form.addRow("Spacing", self.spacing)

        self.extrude = QtWidgets.QSpinBox()
        self.extrude.setRange(0, 4096)
        self.extrude.setToolTip("Extrude each tile's edges to prevent tearing (px)")
        advanced_form.addRow("Extrude", self.extrude)

        # Resize mode -----------------------------------------------------
        self.resize_mode = QtWidgets.QComboBox()
        self.resize_mode.addItems(sorted(RESIZE_MODES))
        self.resize_mode.setToolTip("How tiles are fitted into the cell size")
        advanced_form.addRow("Resize mode", self.resize_mode)

        # Name ------------------------------------------------------------
        self.name = QtWidgets.QLineEdit("tileset")
        self.name.setToolTip("Tileset name (written into the .tsx/.tsj)")
        advanced_form.addRow("Name", self.name)

        # Background ------------------------------------------------------
        bg_row = QtWidgets.QWidget()
        bg_layout = QtWidgets.QHBoxLayout(bg_row)
        bg_layout.setContentsMargins(0, 0, 0, 0)
        self.background_button = QtWidgets.QPushButton()
        self.background_button.setToolTip("Tileset background color")
        self.background_transparent = QtWidgets.QCheckBox("Transparent")
        self.background_transparent.setToolTip(
            "When checked, the tileset background is transparent (None)"
        )
        bg_layout.addWidget(self.background_button, 1)
        bg_layout.addWidget(self.background_transparent)
        advanced_form.addRow("Background", bg_row)

        # The color last chosen via the dialog; used when un-toggling transparent.
        self._background_color: RGBA = (0, 0, 0, 255)

        # Fit-to-cell -----------------------------------------------------
        self.fit_to_cell = QtWidgets.QCheckBox("Fit each tile to one cell")
        self.fit_to_cell.setToolTip(
            "Off: keep each image size (large images span multiple cells). "
            "On: shrink every image into one cell."
        )
        advanced_form.addRow("", self.fit_to_cell)

        # Wire signals ----------------------------------------------------
        self.orientation.currentTextChanged.connect(self._on_orientation)
        self.tile_width.currentTextChanged.connect(self._on_tile_width)
        self.tile_height.currentTextChanged.connect(self._on_tile_height)
        self.columns.valueChanged.connect(self._on_columns)
        self.rows.valueChanged.connect(self._on_rows)
        self.margin.valueChanged.connect(self._on_margin)
        self.spacing.valueChanged.connect(self._on_spacing)
        self.extrude.valueChanged.connect(self._on_extrude)
        self.resize_mode.currentTextChanged.connect(self._on_resize_mode)
        self.name.textChanged.connect(self._on_name)
        self.background_button.clicked.connect(self._on_pick_background)
        self.background_transparent.toggled.connect(self._on_background_transparent)
        self.fit_to_cell.toggled.connect(self._on_fit_to_cell)
        self.advanced_toggle.toggled.connect(self._on_toggle_advanced)

        self._sync_from_grid()

    def _on_toggle_advanced(self, expanded: bool) -> None:
        """Show or hide the advanced grid/tileset controls."""
        self.advanced_container.setVisible(expanded)
        self.advanced_toggle.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if expanded else QtCore.Qt.ArrowType.RightArrow
        )

    # -- Binding ----------------------------------------------------------
    def bind(self, grid: GridSettings) -> None:
        """Bind to a different :class:`GridSettings` and sync the widgets to it."""
        self._grid = grid
        self._sync_from_grid()

    def _sync_from_grid(self) -> None:
        """Push the bound grid's values into the widgets without emitting changed."""
        self._updating = True
        try:
            g = self._grid
            idx = self.orientation.findText(g.orientation)
            self.orientation.setCurrentIndex(idx if idx >= 0 else 0)
            _set_size_combo(self.tile_width, g.tile_width)
            _set_size_combo(self.tile_height, g.tile_height)
            self.columns.setValue(int(g.columns))
            self.rows.setValue(int(g.rows))
            self.margin.setValue(int(g.margin))
            self.spacing.setValue(int(g.spacing))
            self.extrude.setValue(int(g.extrude))
            ridx = self.resize_mode.findText(g.resize_mode)
            self.resize_mode.setCurrentIndex(ridx if ridx >= 0 else 0)
            self.name.setText(g.name)
            if g.background is not None:
                self._background_color = g.background
            self.background_transparent.setChecked(g.background is None)
            self._refresh_background_button()
            self.fit_to_cell.setChecked(bool(g.fit_to_cell))
        finally:
            self._updating = False
        self._refresh_dependent_enabled()
        # Auto-expand the advanced section if this grid uses any advanced value
        # (e.g. a loaded workspace), so those settings are never hidden.
        if self._grid_has_advanced() and not self.advanced_toggle.isChecked():
            self.advanced_toggle.setChecked(True)

    def _grid_has_advanced(self) -> bool:
        """Return ``True`` if any advanced grid value is non-default."""
        g = self._grid
        return bool(g.margin or g.spacing or g.extrude or g.fit_to_cell)

    def _refresh_dependent_enabled(self) -> None:
        """Enable margin/spacing/extrude/resize-mode only in 'fit to cell' mode.

        In the default keep-size export these settings have no effect, so they
        are disabled with an explanatory tooltip to avoid confusion.
        """
        fit = self.fit_to_cell.isChecked()
        hint = "" if fit else "  (only used when 'Fit each tile to one cell' is on)"
        for widget, base in (
            (self.margin, "Outer margin around the tileset (px)"),
            (self.spacing, "Spacing between tiles (px)"),
            (self.extrude, "Extrude each tile's edges to prevent tearing (px)"),
            (self.resize_mode, "How tiles are fitted into the cell size"),
        ):
            widget.setEnabled(fit)
            widget.setToolTip(base + hint)

    def _refresh_background_button(self) -> None:
        """Update the background swatch from the current grid/transparent state."""
        transparent = self.background_transparent.isChecked()
        self.background_button.setEnabled(not transparent)
        color = None if transparent else self._background_color
        _style_color_button(self.background_button, color, none_text="Transparent")

    def _emit(self) -> None:
        """Emit :attr:`changed` unless we are mid programmatic sync."""
        if not self._updating:
            self.changed.emit()

    # -- Slots ------------------------------------------------------------
    def _on_orientation(self, text: str) -> None:
        if self._updating:
            return
        self._grid.orientation = text
        self._emit()

    def _on_tile_width(self, text: str) -> None:
        if self._updating or not text:
            return
        self._grid.tile_width = int(text)
        self._emit()

    def _on_tile_height(self, text: str) -> None:
        if self._updating or not text:
            return
        self._grid.tile_height = int(text)
        self._emit()

    def _on_columns(self, value: int) -> None:
        if self._updating:
            return
        self._grid.columns = int(value)
        self._emit()

    def _on_rows(self, value: int) -> None:
        if self._updating:
            return
        self._grid.rows = int(value)
        self._emit()

    def _on_margin(self, value: int) -> None:
        if self._updating:
            return
        self._grid.margin = int(value)
        self._emit()

    def _on_spacing(self, value: int) -> None:
        if self._updating:
            return
        self._grid.spacing = int(value)
        self._emit()

    def _on_extrude(self, value: int) -> None:
        if self._updating:
            return
        self._grid.extrude = int(value)
        self._emit()

    def _on_resize_mode(self, text: str) -> None:
        if self._updating:
            return
        self._grid.resize_mode = text
        self._emit()

    def _on_name(self, text: str) -> None:
        if self._updating:
            return
        self._grid.name = text
        self._emit()

    def _on_pick_background(self) -> None:
        if self._updating:
            return
        chosen = QtWidgets.QColorDialog.getColor(
            _rgba_to_qcolor(self._background_color),
            self,
            "Background color",
            QtWidgets.QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not chosen.isValid():
            return
        self._background_color = _qcolor_to_rgba(chosen)
        # Picking a color implies a non-transparent background.
        self._updating = True
        try:
            self.background_transparent.setChecked(False)
        finally:
            self._updating = False
        self._refresh_background_button()
        self._grid.background = self._background_color
        self._emit()

    def _on_background_transparent(self, transparent: bool) -> None:
        self._refresh_background_button()
        if self._updating:
            return
        if transparent:
            self._grid.background = None
        else:
            # parse_color normalizes the stored swatch into an RGBA tuple.
            self._grid.background = parse_color(list(self._background_color))
        self._emit()

    def _on_fit_to_cell(self, checked: bool) -> None:
        self._refresh_dependent_enabled()
        if self._updating:
            return
        self._grid.fit_to_cell = bool(checked)
        self._emit()


class EditPanel(QtWidgets.QWidget):
    """Editor for the currently selected tile's :class:`TileEdit`.

    Call :meth:`set_tile` with the selected :class:`TileItem` (or ``None`` to
    disable the panel). Every widget change writes into ``tile.edit`` and emits
    :attr:`changed`.
    """

    #: Emitted after a user edit has been written into the selected tile's edit.
    changed = QtCore.Signal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        """Build the panel (disabled until a tile is set)."""
        super().__init__(parent)
        self._tile: Optional[TileItem] = None
        self._updating = False

        outer = QtWidgets.QVBoxLayout(self)

        # Basic adjustments (always visible): size, rotation, flip. These are
        # the controls a first-time user needs; everything else lives under a
        # collapsible "Advanced" section below to keep the panel uncluttered.
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        outer.addLayout(form)

        # Size (display-size scale, 10..400 percent -> edit.scale) --------
        size_row = QtWidgets.QWidget()
        size_layout = QtWidgets.QHBoxLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        self.scale = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.scale.setRange(10, 400)
        self.scale.setValue(100)
        self.scale.setToolTip(
            "Display-size multiplier (same value as dragging the corner handles)"
        )
        self.scale_label = QtWidgets.QLabel("100%")
        self.scale_label.setMinimumWidth(40)
        self.scale_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.reset_scale_button = QtWidgets.QPushButton("Reset size (100%)")
        self.reset_scale_button.setToolTip("Reset the tile display size back to 100%")
        size_layout.addWidget(self.scale, 1)
        size_layout.addWidget(self.scale_label)
        size_layout.addWidget(self.reset_scale_button)
        form.addRow("Size", size_row)

        # Rotation --------------------------------------------------------
        rot_row = QtWidgets.QWidget()
        rot_layout = QtWidgets.QHBoxLayout(rot_row)
        rot_layout.setContentsMargins(0, 0, 0, 0)
        self.rotation = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.rotation.setRange(-180, 180)
        self.rotation.setToolTip("Rotation in degrees (counter-clockwise)")
        self.rotation_label = QtWidgets.QLabel("0")
        self.rotation_label.setMinimumWidth(36)
        self.rotation_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        rot_layout.addWidget(self.rotation, 1)
        rot_layout.addWidget(self.rotation_label)
        form.addRow("Rotation", rot_row)

        # Flip ------------------------------------------------------------
        flip_row = QtWidgets.QWidget()
        flip_layout = QtWidgets.QHBoxLayout(flip_row)
        flip_layout.setContentsMargins(0, 0, 0, 0)
        self.flip_h = QtWidgets.QCheckBox("Horizontal")
        self.flip_v = QtWidgets.QCheckBox("Vertical")
        flip_layout.addWidget(self.flip_h)
        flip_layout.addWidget(self.flip_v)
        flip_layout.addStretch(1)
        form.addRow("Flip", flip_row)

        # Numeric crop (px cut from each side of the SOURCE) --------------
        # Source-space so it works regardless of rotation/trim, and lets the
        # user crop precisely when the small on-canvas handles are hard to grab.
        # ↑/↓ nudge by 1px; PageUp/Down by 10px.
        self.crop_left = QtWidgets.QSpinBox()
        self.crop_top = QtWidgets.QSpinBox()
        self.crop_right = QtWidgets.QSpinBox()
        self.crop_bottom = QtWidgets.QSpinBox()
        self._crop_spins = (self.crop_left, self.crop_top, self.crop_right, self.crop_bottom)
        for sb, tip in (
            (self.crop_left, "Pixels cropped from the LEFT (source pixels)"),
            (self.crop_top, "Pixels cropped from the TOP (source pixels)"),
            (self.crop_right, "Pixels cropped from the RIGHT (source pixels)"),
            (self.crop_bottom, "Pixels cropped from the BOTTOM (source pixels)"),
        ):
            sb.setRange(0, 1_000_000)
            sb.setKeyboardTracking(False)
            sb.setToolTip(tip + " — ↑/↓ = ±1px, PageUp/Down = ±10px")
        crop_grid_w = QtWidgets.QWidget()
        crop_grid = QtWidgets.QGridLayout(crop_grid_w)
        crop_grid.setContentsMargins(0, 0, 0, 0)
        crop_grid.setHorizontalSpacing(6)
        crop_grid.setVerticalSpacing(2)
        crop_grid.addWidget(QtWidgets.QLabel("L"), 0, 0)
        crop_grid.addWidget(self.crop_left, 0, 1)
        crop_grid.addWidget(QtWidgets.QLabel("T"), 0, 2)
        crop_grid.addWidget(self.crop_top, 0, 3)
        crop_grid.addWidget(QtWidgets.QLabel("R"), 1, 0)
        crop_grid.addWidget(self.crop_right, 1, 1)
        crop_grid.addWidget(QtWidgets.QLabel("B"), 1, 2)
        crop_grid.addWidget(self.crop_bottom, 1, 3)
        form.addRow("Crop (px)", crop_grid_w)

        # Advanced section toggle ----------------------------------------
        # A flat, full-width button that expands/collapses the color and
        # background controls. Collapsed by default so the panel stays simple.
        self.advanced_toggle = QtWidgets.QToolButton()
        self.advanced_toggle.setText("Advanced: color, background, resize")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.advanced_toggle.setArrowType(QtCore.Qt.ArrowType.RightArrow)
        self.advanced_toggle.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.advanced_toggle.setStyleSheet(
            "QToolButton { border: none; font-weight: bold; padding: 4px 0; }"
        )
        self.advanced_toggle.setToolTip(
            "Show color correction, background removal and resize-mode options"
        )
        outer.addWidget(self.advanced_toggle)

        # Everything below lives inside a collapsible container.
        self.advanced_container = QtWidgets.QWidget()
        advanced_form = QtWidgets.QFormLayout(self.advanced_container)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        advanced_form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        outer.addWidget(self.advanced_container)
        self.advanced_container.setVisible(False)

        # Hue -------------------------------------------------------------
        hue_row = QtWidgets.QWidget()
        hue_layout = QtWidgets.QHBoxLayout(hue_row)
        hue_layout.setContentsMargins(0, 0, 0, 0)
        self.hue = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.hue.setRange(-180, 180)
        self.hue.setToolTip("Hue rotation in degrees")
        self.hue_label = QtWidgets.QLabel("0")
        self.hue_label.setMinimumWidth(36)
        self.hue_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        hue_layout.addWidget(self.hue, 1)
        hue_layout.addWidget(self.hue_label)
        advanced_form.addRow("Hue", hue_row)

        # Saturation / brightness / contrast (0..200 -> 0.00..2.00) -------
        self.saturation, sat_row, self.saturation_label = self._make_factor_slider(
            "Color saturation multiplier"
        )
        advanced_form.addRow("Saturation", sat_row)
        self.brightness, bri_row, self.brightness_label = self._make_factor_slider(
            "Brightness multiplier"
        )
        advanced_form.addRow("Brightness", bri_row)
        self.contrast, con_row, self.contrast_label = self._make_factor_slider(
            "Contrast multiplier"
        )
        advanced_form.addRow("Contrast", con_row)

        # Grayscale / trim ------------------------------------------------
        gt_row = QtWidgets.QWidget()
        gt_layout = QtWidgets.QHBoxLayout(gt_row)
        gt_layout.setContentsMargins(0, 0, 0, 0)
        self.grayscale = QtWidgets.QCheckBox("Grayscale")
        self.trim = QtWidgets.QCheckBox("Trim")
        self.trim.setToolTip("Crop transparent borders")
        gt_layout.addWidget(self.grayscale)
        gt_layout.addWidget(self.trim)
        gt_layout.addStretch(1)
        advanced_form.addRow("Adjust", gt_row)

        # Background removal ----------------------------------------------
        self.bg_remove = QtWidgets.QCheckBox("Remove background")
        advanced_form.addRow("", self.bg_remove)

        bgc_row = QtWidgets.QWidget()
        bgc_layout = QtWidgets.QHBoxLayout(bgc_row)
        bgc_layout.setContentsMargins(0, 0, 0, 0)
        self.bg_color_button = QtWidgets.QPushButton()
        self.bg_color_button.setToolTip("Background color to remove (auto = corners)")
        self.bg_color_auto = QtWidgets.QPushButton("Auto")
        self.bg_color_auto.setToolTip("Reset background color to auto (corner sampling)")
        bgc_layout.addWidget(self.bg_color_button, 1)
        bgc_layout.addWidget(self.bg_color_auto)
        advanced_form.addRow("BG color", bgc_row)

        tol_row = QtWidgets.QWidget()
        tol_layout = QtWidgets.QHBoxLayout(tol_row)
        tol_layout.setContentsMargins(0, 0, 0, 0)
        self.bg_tolerance = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.bg_tolerance.setRange(0, 441)
        self.bg_tolerance.setToolTip("Color distance tolerance (0..441)")
        self.bg_tolerance_label = QtWidgets.QLabel("0")
        self.bg_tolerance_label.setMinimumWidth(36)
        self.bg_tolerance_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        tol_layout.addWidget(self.bg_tolerance, 1)
        tol_layout.addWidget(self.bg_tolerance_label)
        advanced_form.addRow("BG tolerance", tol_row)

        self.bg_flood = QtWidgets.QCheckBox("Flood fill from corners")
        advanced_form.addRow("", self.bg_flood)

        # Resize-mode override --------------------------------------------
        self.resize_mode = QtWidgets.QComboBox()
        self.resize_mode.addItems([_GRID_DEFAULT] + sorted(RESIZE_MODES))
        self.resize_mode.setToolTip("Per-tile resize mode (or inherit the grid default)")
        advanced_form.addRow("Resize mode", self.resize_mode)

        # Buttons ---------------------------------------------------------
        btn_row = QtWidgets.QWidget()
        btn_layout = QtWidgets.QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        self.reset_crop_button = QtWidgets.QPushButton("Reset crop")
        self.reset_all_button = QtWidgets.QPushButton("Reset all edits")
        btn_layout.addWidget(self.reset_crop_button)
        btn_layout.addWidget(self.reset_all_button)
        outer.addWidget(btn_row)
        outer.addStretch(1)

        # The color last chosen via the dialog for bg removal (None = auto).
        self._bg_color: Optional[RGBA] = None

        # Wire signals ----------------------------------------------------
        self.scale.valueChanged.connect(self._on_scale)
        self.reset_scale_button.clicked.connect(self._on_reset_scale)
        self.rotation.valueChanged.connect(self._on_rotation)
        self.flip_h.toggled.connect(self._on_flip_h)
        self.flip_v.toggled.connect(self._on_flip_v)
        self.hue.valueChanged.connect(self._on_hue)
        self.saturation.valueChanged.connect(self._on_saturation)
        self.brightness.valueChanged.connect(self._on_brightness)
        self.contrast.valueChanged.connect(self._on_contrast)
        self.grayscale.toggled.connect(self._on_grayscale)
        self.trim.toggled.connect(self._on_trim)
        self.bg_remove.toggled.connect(self._on_bg_remove)
        self.bg_color_button.clicked.connect(self._on_pick_bg_color)
        self.bg_color_auto.clicked.connect(self._on_bg_color_auto)
        self.bg_tolerance.valueChanged.connect(self._on_bg_tolerance)
        self.bg_flood.toggled.connect(self._on_bg_flood)
        self.resize_mode.currentTextChanged.connect(self._on_resize_mode)
        for sb in self._crop_spins:
            sb.valueChanged.connect(self._on_crop_margin_changed)
        self.reset_crop_button.clicked.connect(self._on_reset_crop)
        self.reset_all_button.clicked.connect(self._on_reset_all)
        self.advanced_toggle.toggled.connect(self._on_toggle_advanced)

        self.setEnabled(False)

    def _on_toggle_advanced(self, expanded: bool) -> None:
        """Show or hide the advanced color/background/resize controls."""
        self.advanced_container.setVisible(expanded)
        self.advanced_toggle.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if expanded else QtCore.Qt.ArrowType.RightArrow
        )

    def _make_factor_slider(self, tooltip: str):
        """Build a 0..200 slider (shown as 0.00..2.00) with its row and value label."""
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        slider.setRange(0, 200)
        slider.setValue(100)
        slider.setToolTip(tooltip)
        label = QtWidgets.QLabel("1.00")
        label.setMinimumWidth(36)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addWidget(slider, 1)
        layout.addWidget(label)
        return slider, row, label

    # -- Public API -------------------------------------------------------
    def set_tile(self, tile_item: Optional[TileItem]) -> None:
        """Bind the panel to ``tile_item`` (or disable it when ``None``)."""
        self._tile = tile_item
        if tile_item is None:
            self.setEnabled(False)
            return
        self.setEnabled(True)
        self._sync_from_edit()
        # Auto-expand the advanced section when this tile actually uses any of
        # its controls, so the active edits are never hidden. We never auto
        # collapse: once the user opens it, it stays open.
        if self._edit_has_advanced(tile_item.edit) and not self.advanced_toggle.isChecked():
            self.advanced_toggle.setChecked(True)

    @staticmethod
    def _edit_has_advanced(edit) -> bool:
        """Return ``True`` if any advanced (color/bg/resize) value is non-default."""
        return (
            round(edit.hue) != 0
            or abs(edit.saturation - 1.0) > 1e-6
            or abs(edit.brightness - 1.0) > 1e-6
            or abs(edit.contrast - 1.0) > 1e-6
            or bool(edit.grayscale)
            or bool(edit.trim)
            or bool(edit.bg_remove)
            or edit.resize_mode is not None
        )

    def _sync_from_edit(self) -> None:
        """Push the selected tile's edit values into the widgets (no emit)."""
        if self._tile is None:
            return
        e = self._tile.edit
        self._updating = True
        try:
            scale_pct = int(round((e.scale if e.scale > 0 else 1.0) * 100))
            scale_pct = max(self.scale.minimum(), min(self.scale.maximum(), scale_pct))
            self.scale.setValue(scale_pct)
            self.scale_label.setText(f"{scale_pct}%")
            self.rotation.setValue(int(round(e.rotation)))
            self.rotation_label.setText(f"{int(round(e.rotation))}")
            self.flip_h.setChecked(bool(e.flip_h))
            self.flip_v.setChecked(bool(e.flip_v))
            self.hue.setValue(int(round(e.hue)))
            self.hue_label.setText(f"{int(round(e.hue))}")
            self._set_factor(self.saturation, self.saturation_label, e.saturation)
            self._set_factor(self.brightness, self.brightness_label, e.brightness)
            self._set_factor(self.contrast, self.contrast_label, e.contrast)
            self.grayscale.setChecked(bool(e.grayscale))
            self.trim.setChecked(bool(e.trim))
            self.bg_remove.setChecked(bool(e.bg_remove))
            self._bg_color = e.bg_color
            _style_color_button(self.bg_color_button, e.bg_color, none_text="Auto")
            self.bg_tolerance.setValue(int(e.bg_tolerance))
            self.bg_tolerance_label.setText(f"{int(e.bg_tolerance)}")
            self.bg_flood.setChecked(bool(e.bg_flood))
            text = e.resize_mode if e.resize_mode is not None else _GRID_DEFAULT
            ridx = self.resize_mode.findText(text)
            self.resize_mode.setCurrentIndex(ridx if ridx >= 0 else 0)
            self._sync_crop_spins(e)
        finally:
            self._updating = False

    def _sync_crop_spins(self, edit) -> None:
        """Push the current source crop into the L/T/R/B margin spin boxes.

        Assumes ``self._updating`` is True (called from :meth:`_sync_from_edit`).
        """
        if self._tile is None:
            return
        sw, sh = self._tile.source.size
        for sb, hi in (
            (self.crop_left, sw), (self.crop_right, sw),
            (self.crop_top, sh), (self.crop_bottom, sh),
        ):
            sb.setMaximum(max(0, hi))
        crop = edit.crop
        if crop is None:
            left = top = right_m = bottom_m = 0
        else:
            cl, ct, cr, cb = crop
            left = cl
            top = ct
            right_m = sw - cr
            bottom_m = sh - cb
        self.crop_left.setValue(int(left))
        self.crop_top.setValue(int(top))
        self.crop_right.setValue(int(right_m))
        self.crop_bottom.setValue(int(bottom_m))

    @staticmethod
    def _set_factor(slider: QtWidgets.QSlider, label: QtWidgets.QLabel, factor: float) -> None:
        """Set a factor slider (0..2.00) and its label from a float multiplier."""
        value = int(round(factor * 100))
        value = max(0, min(200, value))
        slider.setValue(value)
        label.setText(f"{value / 100:.2f}")

    def _emit(self) -> None:
        """Emit :attr:`changed` unless we are mid programmatic sync."""
        if not self._updating:
            self.changed.emit()

    # -- Slots ------------------------------------------------------------
    def _on_scale(self, value: int) -> None:
        self.scale_label.setText(f"{int(value)}%")
        if self._updating or self._tile is None:
            return
        self._tile.edit.scale = value / 100.0
        self._emit()

    def _on_reset_scale(self) -> None:
        if self._updating or self._tile is None:
            return
        self._tile.edit.scale = 1.0
        self._updating = True
        try:
            self.scale.setValue(100)
            self.scale_label.setText("100%")
        finally:
            self._updating = False
        self._emit()

    def _on_rotation(self, value: int) -> None:
        self.rotation_label.setText(f"{int(value)}")
        if self._updating or self._tile is None:
            return
        self._tile.edit.rotation = float(value)
        self._emit()

    def _on_flip_h(self, checked: bool) -> None:
        if self._updating or self._tile is None:
            return
        self._tile.edit.flip_h = bool(checked)
        self._emit()

    def _on_flip_v(self, checked: bool) -> None:
        if self._updating or self._tile is None:
            return
        self._tile.edit.flip_v = bool(checked)
        self._emit()

    def _on_hue(self, value: int) -> None:
        self.hue_label.setText(f"{int(value)}")
        if self._updating or self._tile is None:
            return
        self._tile.edit.hue = float(value)
        self._emit()

    def _on_saturation(self, value: int) -> None:
        self.saturation_label.setText(f"{value / 100:.2f}")
        if self._updating or self._tile is None:
            return
        self._tile.edit.saturation = value / 100.0
        self._emit()

    def _on_brightness(self, value: int) -> None:
        self.brightness_label.setText(f"{value / 100:.2f}")
        if self._updating or self._tile is None:
            return
        self._tile.edit.brightness = value / 100.0
        self._emit()

    def _on_contrast(self, value: int) -> None:
        self.contrast_label.setText(f"{value / 100:.2f}")
        if self._updating or self._tile is None:
            return
        self._tile.edit.contrast = value / 100.0
        self._emit()

    def _on_grayscale(self, checked: bool) -> None:
        if self._updating or self._tile is None:
            return
        self._tile.edit.grayscale = bool(checked)
        self._emit()

    def _on_trim(self, checked: bool) -> None:
        if self._updating or self._tile is None:
            return
        self._tile.edit.trim = bool(checked)
        self._emit()

    def _on_bg_remove(self, checked: bool) -> None:
        if self._updating or self._tile is None:
            return
        self._tile.edit.bg_remove = bool(checked)
        self._emit()

    def _on_pick_bg_color(self) -> None:
        if self._updating or self._tile is None:
            return
        chosen = QtWidgets.QColorDialog.getColor(
            _rgba_to_qcolor(self._bg_color),
            self,
            "Background color to remove",
            QtWidgets.QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not chosen.isValid():
            return
        self._bg_color = _qcolor_to_rgba(chosen)
        _style_color_button(self.bg_color_button, self._bg_color, none_text="Auto")
        self._tile.edit.bg_color = self._bg_color
        self._emit()

    def _on_bg_color_auto(self) -> None:
        if self._updating or self._tile is None:
            return
        self._bg_color = None
        _style_color_button(self.bg_color_button, None, none_text="Auto")
        self._tile.edit.bg_color = None
        self._emit()

    def _on_bg_tolerance(self, value: int) -> None:
        self.bg_tolerance_label.setText(f"{int(value)}")
        if self._updating or self._tile is None:
            return
        self._tile.edit.bg_tolerance = int(value)
        self._emit()

    def _on_bg_flood(self, checked: bool) -> None:
        if self._updating or self._tile is None:
            return
        self._tile.edit.bg_flood = bool(checked)
        self._emit()

    def _on_resize_mode(self, text: str) -> None:
        if self._updating or self._tile is None:
            return
        self._tile.edit.resize_mode = None if text == _GRID_DEFAULT else text
        self._emit()

    def _on_crop_margin_changed(self) -> None:
        """Apply the L/T/R/B margin spin boxes as a source-space crop.

        Each value is pixels cut from that side of the *source* image, so this
        works regardless of rotation/trim (unlike the on-canvas crop). Opposite
        margins are clamped so at least a 1px region remains.
        """
        if self._updating or self._tile is None:
            return
        sw, sh = self._tile.source.size
        self._updating = True
        try:
            left = min(self.crop_left.value(), max(0, sw - 1))
            right_m = min(self.crop_right.value(), max(0, sw - 1 - left))
            top = min(self.crop_top.value(), max(0, sh - 1))
            bottom_m = min(self.crop_bottom.value(), max(0, sh - 1 - top))
            # Write back the clamped values so the UI reflects what was applied.
            self.crop_left.setValue(left)
            self.crop_right.setValue(right_m)
            self.crop_top.setValue(top)
            self.crop_bottom.setValue(bottom_m)
        finally:
            self._updating = False
        right = sw - right_m
        bottom = sh - bottom_m
        if (left, top, right, bottom) == (0, 0, sw, sh):
            self._tile.edit.crop = None
        else:
            self._tile.edit.crop = (left, top, right, bottom)
        self._emit()

    def _on_reset_crop(self) -> None:
        if self._updating or self._tile is None:
            return
        self._tile.edit.crop = None
        self._updating = True
        try:
            for sb in self._crop_spins:
                sb.setValue(0)
        finally:
            self._updating = False
        self._emit()

    def _on_reset_all(self) -> None:
        if self._updating or self._tile is None:
            return
        self._tile.edit.reset()
        self._sync_from_edit()
        self._emit()
