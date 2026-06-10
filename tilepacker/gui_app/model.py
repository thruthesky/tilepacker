"""Project data model for the GUI: tiles, per-tile edits, and grid settings.

This module is pure (no Qt). It holds the editable project state and knows how
to render each tile through its edit pipeline and export the whole project as a
tileset (PNG + .tsx/.tsj) by reusing the core packing/export code.

Edit pipeline order (non-destructive, re-applied from the source every time):

    source -> crop -> rotate -> flip -> grayscale -> hue -> saturation
           -> brightness -> contrast -> remove background -> trim

The display-size scaling (and any cell fitting) happens after that, so changing
the grid size or the scale never loses edit information.

Dependencies: Pillow + core submodules.
"""

from __future__ import annotations

import copy
import json
import math
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image

from tilepacker.core import imageops, export, tiled
from tilepacker.core.config import PackConfig, RGBA
from tilepacker.gui_app import imageedit

__all__ = [
    "TileEdit",
    "GridSettings",
    "TileItem",
    "ProjectModel",
    "TilesetExportResult",
    "ORIENTATIONS",
    "ALIGNMENTS",
    "WORKSPACE_VERSION",
]

#: Supported tile grid orientations.
ORIENTATIONS = ("isometric", "orthogonal")

#: Tile alignments within a cell span (used by the preview right-click menu).
ALIGNMENTS = ("topleft", "center", "left", "right", "top", "bottom")


def _align_offset(align: str, span_w: int, span_h: int, img_w: int, img_h: int):
    """Pixel offset to place a ``img_w x img_h`` image inside a ``span`` cell area.

    ``align`` is one of :data:`ALIGNMENTS`. Horizontal-only choices keep the tile
    vertically centered, and vice-versa.
    """
    free_x = max(0, span_w - img_w)
    free_y = max(0, span_h - img_h)
    if align == "center":
        return free_x / 2, free_y / 2
    if align == "left":
        return 0, free_y / 2
    if align == "right":
        return free_x, free_y / 2
    if align == "top":
        return free_x / 2, 0
    if align == "bottom":
        return free_x / 2, free_y
    return 0, 0  # topleft (default)

#: Schema version stamped into saved workspace files.
WORKSPACE_VERSION = 1

#: Maximum number of undo states kept in the history stack.
_HISTORY_LIMIT = 100


@dataclass
class TileEdit:
    """Non-destructive edit parameters applied to a single tile's source image.

    All fields default to a no-op so a freshly imported tile is unmodified.
    """

    crop: Optional[Tuple[int, int, int, int]] = None  # (left, top, right, bottom)
    rotation: float = 0.0          # degrees, counter-clockwise
    flip_h: bool = False
    flip_v: bool = False
    grayscale: bool = False
    hue: float = 0.0               # -180..180 degrees
    saturation: float = 1.0        # 1.0 = unchanged
    brightness: float = 1.0        # 1.0 = unchanged
    contrast: float = 1.0          # 1.0 = unchanged
    bg_remove: bool = False
    bg_color: Optional[RGBA] = None
    bg_tolerance: int = 0
    bg_flood: bool = False
    trim: bool = False
    diamond: bool = False          # mask to the tile-ratio diamond (isometric cut)
    resize_mode: Optional[str] = None  # None = inherit the grid's resize_mode
    scale: float = 1.0   # display-size multiplier, set by dragging the corner handles
    align: str = "topleft"   # placement within its cell span: topleft|center|left|right|top|bottom

    def reset(self) -> None:
        """Reset every field back to its no-op default."""
        fresh = TileEdit()
        for f in fresh.__dataclass_fields__:
            setattr(self, f, getattr(fresh, f))

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict (tuples become lists)."""
        return {
            "crop": list(self.crop) if self.crop is not None else None,
            "rotation": self.rotation,
            "flip_h": self.flip_h,
            "flip_v": self.flip_v,
            "grayscale": self.grayscale,
            "hue": self.hue,
            "saturation": self.saturation,
            "brightness": self.brightness,
            "contrast": self.contrast,
            "bg_remove": self.bg_remove,
            "bg_color": list(self.bg_color) if self.bg_color is not None else None,
            "bg_tolerance": self.bg_tolerance,
            "bg_flood": self.bg_flood,
            "trim": self.trim,
            "diamond": self.diamond,
            "resize_mode": self.resize_mode,
            "scale": self.scale,
            "align": self.align,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "TileEdit":
        """Build a :class:`TileEdit` from a dict, tolerating missing keys."""
        e = cls()
        if not isinstance(data, dict):
            return e
        crop = data.get("crop")
        e.crop = tuple(int(v) for v in crop) if crop else None
        e.rotation = float(data.get("rotation", e.rotation))
        e.flip_h = bool(data.get("flip_h", e.flip_h))
        e.flip_v = bool(data.get("flip_v", e.flip_v))
        e.grayscale = bool(data.get("grayscale", e.grayscale))
        e.hue = float(data.get("hue", e.hue))
        e.saturation = float(data.get("saturation", e.saturation))
        e.brightness = float(data.get("brightness", e.brightness))
        e.contrast = float(data.get("contrast", e.contrast))
        e.bg_remove = bool(data.get("bg_remove", e.bg_remove))
        bg = data.get("bg_color")
        e.bg_color = tuple(int(v) for v in bg) if bg else None
        e.bg_tolerance = int(data.get("bg_tolerance", e.bg_tolerance))
        e.bg_flood = bool(data.get("bg_flood", e.bg_flood))
        e.trim = bool(data.get("trim", e.trim))
        e.diamond = bool(data.get("diamond", e.diamond))
        e.resize_mode = data.get("resize_mode", e.resize_mode)
        e.scale = float(data.get("scale", e.scale))
        e.align = data.get("align", e.align)
        return e


@dataclass
class GridSettings:
    """Tileset grid configuration shared by all tiles.

    Defaults target isometric tiles (64x32), a common 2:1 isometric cell size,
    as requested for the default project.
    """

    orientation: str = "isometric"   # one of ORIENTATIONS
    tile_width: int = 64
    tile_height: int = 32
    columns: int = 8                 # default 8-wide tileset grid (0 = auto)
    margin: int = 0
    spacing: int = 0
    extrude: int = 0
    resize_mode: str = "fit"         # default cell-fit mode (only used when fit_to_cell)
    background: Optional[RGBA] = None
    name: str = "tileset"
    # When False (default), each tile keeps its own (scaled) pixel size and may
    # span several grid cells. When True, every tile is resized into a single
    # cell (the classic uniform-grid tileset).
    fit_to_cell: bool = False

    def to_pack_config(self) -> PackConfig:
        """Build a :class:`PackConfig` for packing pre-fitted cells.

        Tiles are already resized to the cell size by the time they reach the
        packer, so ``resize_mode`` is set to ``"none"`` here to avoid a second
        resize. Extrude/margin/spacing/background are honored by the packer.
        """
        return PackConfig(
            tile_width=self.tile_width,
            tile_height=self.tile_height,
            columns=self.columns,
            margin=self.margin,
            spacing=self.spacing,
            extrude=self.extrude,
            resize_mode="none",
            background=self.background,
            name=self.name,
        )

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict (the background tuple becomes a list)."""
        return {
            "orientation": self.orientation,
            "tile_width": self.tile_width,
            "tile_height": self.tile_height,
            "columns": self.columns,
            "margin": self.margin,
            "spacing": self.spacing,
            "extrude": self.extrude,
            "resize_mode": self.resize_mode,
            "background": list(self.background) if self.background is not None else None,
            "name": self.name,
            "fit_to_cell": self.fit_to_cell,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "GridSettings":
        """Build a :class:`GridSettings` from a dict, tolerating missing keys."""
        g = cls()
        if not isinstance(data, dict):
            return g
        g.orientation = data.get("orientation", g.orientation)
        g.tile_width = int(data.get("tile_width", g.tile_width))
        g.tile_height = int(data.get("tile_height", g.tile_height))
        g.columns = int(data.get("columns", g.columns))
        g.margin = int(data.get("margin", g.margin))
        g.spacing = int(data.get("spacing", g.spacing))
        g.extrude = int(data.get("extrude", g.extrude))
        g.resize_mode = data.get("resize_mode", g.resize_mode)
        bg = data.get("background")
        g.background = tuple(int(v) for v in bg) if bg else None
        g.name = data.get("name", g.name)
        g.fit_to_cell = bool(data.get("fit_to_cell", g.fit_to_cell))
        return g


class TileItem:
    """A single source tile plus its non-destructive edit state."""

    def __init__(self, path: str, source: Image.Image):
        """Create a tile item.

        Args:
            path: Original file path (used for display and as a sort key).
            source: The loaded source image (kept as the immutable RGBA original).
        """
        self.path = path
        self.source = imageops.ensure_rgba(source)
        self.edit = TileEdit()
        # Whether this tile is part of the tileset (shown in the preview and
        # exported). Imported tiles start as sources only; the user explicitly
        # adds the ones they want into the tileset.
        self.in_tileset = False

    @classmethod
    def load(cls, path: str) -> "TileItem":
        """Load a tile item from an image file (any format Pillow can read)."""
        return cls(path, imageops.load_image(path))

    def clone(self) -> "TileItem":
        """Return a copy that shares the immutable source but owns its edit.

        The source image is never mutated by the edit pipeline, so it is shared
        by reference; the :class:`TileEdit` is copied so the clone can be edited
        independently. Used to snapshot undo/redo states cheaply.
        """
        new = TileItem.__new__(TileItem)
        new.path = self.path
        new.source = self.source
        new.edit = copy.copy(self.edit)
        new.in_tileset = self.in_tileset
        return new

    def render(self, grid: Optional["GridSettings"] = None, *, apply_diamond: bool = True) -> Image.Image:
        """Apply the full edit pipeline to the source (without cell resizing).

        Args:
            grid: Active grid, used only to size the ``diamond`` mask to the
                tile's cell ratio. When ``None``, a 1:1 (square) diamond is used.
            apply_diamond: When False, the diamond mask is skipped. The editor
                uses this to show the un-masked source with a diamond *selection*
                outline, while the tileset preview/export keep the mask applied.

        Returns:
            A new RGBA image with all edits applied. The source is never mutated.
        """
        img = self.source
        e = self.edit
        if e.crop is not None:
            img = imageedit.crop_image(img, e.crop)
        if e.rotation % 360 != 0:
            img = imageedit.rotate_image(img, e.rotation)
        if e.flip_h or e.flip_v:
            img = imageedit.flip_image(img, horizontal=e.flip_h, vertical=e.flip_v)
        if e.grayscale:
            img = imageedit.to_grayscale(img)
        if e.hue % 360 != 0:
            img = imageedit.adjust_hue(img, e.hue)
        if e.saturation != 1.0:
            img = imageedit.adjust_saturation(img, e.saturation)
        if e.brightness != 1.0:
            img = imageedit.adjust_brightness(img, e.brightness)
        if e.contrast != 1.0:
            img = imageedit.adjust_contrast(img, e.contrast)
        if e.bg_remove:
            img = imageedit.remove_background(
                img, e.bg_color, e.bg_tolerance, flood=e.bg_flood
            )
        if e.diamond and apply_diamond:
            rw = grid.tile_width if grid is not None else 1
            rh = grid.tile_height if grid is not None else 1
            img = imageedit.diamond_mask(img, rw, rh)
        if e.trim:
            img = imageedit.trim(img)
        # Guarantee a fresh image even when every edit is a no-op.
        if img is self.source:
            img = self.source.copy()
        return img

    def render_cell(self, grid: GridSettings) -> Image.Image:
        """Render the tile and fit it into the grid's cell size.

        Args:
            grid: The active grid settings (cell size + default resize mode).

        Returns:
            A new RGBA image of exactly ``(grid.tile_width, grid.tile_height)``.
        """
        rendered = self.render(grid)
        mode = self.edit.resize_mode or grid.resize_mode
        return imageops.resize_image(
            rendered, (grid.tile_width, grid.tile_height), mode=mode
        )

    def display_image(self, grid: Optional["GridSettings"] = None, *, apply_diamond: bool = True) -> Image.Image:
        """Render the tile at its display size (edits + ``scale``, no cell fitting).

        This preserves the tile's own pixel size (multiplied by ``edit.scale``),
        so a large image stays large and can span several grid cells in both the
        preview and the exported sheet. Pass ``apply_diamond=False`` for the
        editor view (the diamond is shown as a selection outline instead).
        """
        img = self.render(grid, apply_diamond=apply_diamond)
        s = self.edit.scale
        if s > 0 and s != 1.0:
            w = max(1, round(img.width * s))
            h = max(1, round(img.height * s))
            img = img.resize((w, h), Image.Resampling.NEAREST)
        return img

    def display_size(self, grid: Optional["GridSettings"] = None) -> Tuple[int, int]:
        """Return the ``(width, height)`` of the tile at its display size."""
        img = self.render(grid)
        s = self.edit.scale if self.edit.scale > 0 else 1.0
        return (max(1, round(img.width * s)), max(1, round(img.height * s)))

    def cell_span(self, grid: GridSettings) -> Tuple[int, int]:
        """Return how many ``(cols, rows)`` of grid cells this tile occupies."""
        w, h = self.display_size(grid)
        return (
            max(1, math.ceil(w / max(1, grid.tile_width))),
            max(1, math.ceil(h / max(1, grid.tile_height))),
        )

    def thumbnail(self, max_side: int = 96, grid: Optional["GridSettings"] = None) -> Image.Image:
        """Return a small RGBA thumbnail of the rendered tile for list display."""
        img = self.render(grid).copy()
        img.thumbnail((max_side, max_side), Image.Resampling.NEAREST)
        return img


@dataclass
class TilesetExportResult:
    """Result of a GUI tileset export (PNG + optional .tsx/.tsj)."""

    image_path: str
    tsx_path: Optional[str]
    tsj_path: Optional[str]
    tile_count: int     # total number of grid cells in the sheet
    columns: int        # number of cell columns
    rows: int           # number of cell rows
    width: int          # sheet width in pixels
    height: int         # sheet height in pixels


class ProjectModel:
    """The whole editable project: an ordered list of tiles plus grid settings."""

    def __init__(self):
        self.tiles: List[TileItem] = []
        self.grid = GridSettings()
        # Undo/redo history. ``_undo`` holds state snapshots with the most recent
        # (current) state last; ``_redo`` holds states undone past. ``commit`` is
        # called *after* a change to record the new current state.
        self._undo: List[Tuple[List[TileItem], GridSettings]] = [self._snapshot()]
        self._redo: List[Tuple[List[TileItem], GridSettings]] = []
        # The coalesce key of the last commit, so consecutive edits of the same
        # gesture (e.g. dragging a slider) collapse into a single undo step.
        self._last_coalesce: Optional[str] = None

    # -- Undo / redo ----------------------------------------------------
    def _snapshot(self) -> Tuple[List[TileItem], GridSettings]:
        """Capture an independent snapshot of the current project state."""
        return ([t.clone() for t in self.tiles], copy.copy(self.grid))

    def _restore(self, snap: Tuple[List[TileItem], GridSettings]) -> None:
        """Make ``snap`` the live state, re-cloning so the stored copy stays pristine."""
        tiles, grid = snap
        self.tiles = [t.clone() for t in tiles]
        self.grid = copy.copy(grid)

    def commit(self, coalesce: Optional[str] = None) -> None:
        """Record the current state as a new undo step (call after a change).

        Args:
            coalesce: When equal to the previous commit's key, the new state
                replaces the previous top instead of adding a step, so a stream
                of same-gesture edits (e.g. a slider drag) is a single undo.
                Pass ``None`` for discrete actions that should always be their
                own step.
        """
        snap = self._snapshot()
        if coalesce is not None and coalesce == self._last_coalesce and self._undo:
            self._undo[-1] = snap
        else:
            self._undo.append(snap)
            if len(self._undo) > _HISTORY_LIMIT:
                self._undo.pop(0)
        self._redo.clear()
        self._last_coalesce = coalesce

    def reset_history(self) -> None:
        """Clear undo/redo and make the current state the only baseline."""
        self._undo = [self._snapshot()]
        self._redo = []
        self._last_coalesce = None

    def can_undo(self) -> bool:
        """Return whether there is a prior state to undo to."""
        return len(self._undo) > 1

    def can_redo(self) -> bool:
        """Return whether there is an undone state to redo."""
        return bool(self._redo)

    def undo(self) -> bool:
        """Revert to the previous state. Returns ``False`` when there is none."""
        if len(self._undo) <= 1:
            return False
        self._redo.append(self._undo.pop())
        self._restore(self._undo[-1])
        self._last_coalesce = None
        return True

    def redo(self) -> bool:
        """Re-apply the most recently undone state. Returns ``False`` when none."""
        if not self._redo:
            return False
        snap = self._redo.pop()
        self._undo.append(snap)
        self._restore(snap)
        self._last_coalesce = None
        return True

    # -- Workspace persistence ------------------------------------------
    def to_workspace(self) -> dict:
        """Serialize the project (tile source paths + edits + grid) to a dict."""
        return {
            "version": WORKSPACE_VERSION,
            "grid": self.grid.to_dict(),
            "tiles": [{"path": t.path, "edit": t.edit.to_dict()} for t in self.tiles],
        }

    def save_workspace(self, path: str) -> str:
        """Write the project to a JSON workspace file (``.json`` added if needed).

        Returns:
            The path actually written.
        """
        path = os.fspath(path)
        if os.path.splitext(path)[1] == "":
            path = path + ".json"
        out_dir = os.path.dirname(path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_workspace(), fh, indent=2)
        return path

    def load_workspace(self, path: str) -> Tuple[int, List[str]]:
        """Replace the project with the workspace stored at ``path``.

        Each tile's source image is re-loaded from its recorded path; tiles whose
        file can no longer be loaded are skipped. Undo/redo history is reset to
        the loaded state.

        Returns:
            ``(loaded_count, failed_paths)``.
        """
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        grid = GridSettings.from_dict(data.get("grid", {}))
        tiles: List[TileItem] = []
        failed: List[str] = []
        for entry in data.get("tiles", []):
            src = str(entry.get("path", ""))
            try:
                item = TileItem.load(src)
            except Exception:
                failed.append(src)
                continue
            item.edit = TileEdit.from_dict(entry.get("edit", {}))
            tiles.append(item)
        self.tiles = tiles
        self.grid = grid
        self.reset_history()
        return len(tiles), failed

    # -- Tile management ------------------------------------------------
    def add_paths(self, paths) -> Tuple[int, List[str]]:
        """Load and append tiles from the given paths.

        Args:
            paths: Iterable of image file paths.

        Returns:
            ``(added_count, failed_paths)``. Files that fail to load are skipped
            and reported in ``failed_paths`` rather than raising.
        """
        added = 0
        failed: List[str] = []
        for p in paths:
            try:
                self.tiles.append(TileItem.load(str(p)))
                added += 1
            except Exception:
                failed.append(str(p))
        return added, failed

    def remove(self, index: int) -> None:
        """Remove the tile at ``index`` (ignored if out of range)."""
        if 0 <= index < len(self.tiles):
            del self.tiles[index]

    def move(self, index: int, delta: int) -> int:
        """Move the tile at ``index`` by ``delta`` positions; return the new index."""
        if not self.tiles:
            return index
        new = max(0, min(len(self.tiles) - 1, index + delta))
        if new != index:
            self.tiles.insert(new, self.tiles.pop(index))
        return new

    def clear(self) -> None:
        """Remove all tiles."""
        self.tiles.clear()

    def tileset_tiles(self) -> List[TileItem]:
        """Return the tiles the user has added to the tileset (export order)."""
        return [t for t in self.tiles if t.in_tileset]

    def rendered_cells(self) -> List[Image.Image]:
        """Render each tileset tile into its final cell-sized image (export order)."""
        return [t.render_cell(self.grid) for t in self.tileset_tiles()]

    def shelf_layout(self):
        """Place size-preserving tiles onto a cell grid (shelf packing).

        Each tile occupies ``cell_span`` cells. Tiles flow left-to-right; when a
        tile would overflow the column budget the packer starts a new shelf below
        the tallest tile of the current shelf.

        Returns:
            ``(placements, cols_cells, rows_cells)`` where ``placements`` is a
            list of ``(display_image, col, row, off_x, off_y)`` in *cell*
            coordinates; ``off_x/off_y`` are the tile's pixel offset within its
            cell span, from its :attr:`TileEdit.align`.
        """
        grid = self.grid
        cw = max(1, int(grid.tile_width))
        ch = max(1, int(grid.tile_height))
        items = []  # (img, span_cols, span_rows, off_x, off_y)
        for tile in self.tileset_tiles():
            img = tile.display_image(grid)
            sc, sr = tile.cell_span(grid)
            ox, oy = _align_offset(tile.edit.align, sc * cw, sr * ch, img.width, img.height)
            items.append((img, sc, sr, ox, oy))

        max_sc = max((it[1] for it in items), default=1)
        if grid.columns > 0:
            # The grid is exactly this many cells wide; a wider tile is clipped
            # to it horizontally (the height grows downward without limit).
            cols_cells = grid.columns
        else:
            total_cells = sum(it[1] * it[2] for it in items) or 1
            cols_cells = max(max_sc, math.ceil(math.sqrt(total_cells)))

        placements = []
        cur_c = cur_r = shelf_h = 0
        for img, sc, sr, ox, oy in items:
            if cur_c > 0 and cur_c + sc > cols_cells:
                cur_r += shelf_h
                cur_c = 0
                shelf_h = 0
            placements.append((img, cur_c, cur_r, ox, oy))
            cur_c += sc
            shelf_h = max(shelf_h, sr)
        rows_cells = (cur_r + shelf_h) if items else 0
        return placements, cols_cells, rows_cells

    # -- Export ---------------------------------------------------------
    def export(self, out_path: str, *, write_tsx: bool = True, write_tsj: bool = False):
        """Export the project as a tileset (PNG + .tsx/.tsj).

        Two layout modes, selected by ``grid.fit_to_cell``:

        * ``False`` (default): each tile keeps its own scaled size and may span
          several cells (:meth:`shelf_layout`). The image stays at full size.
        * ``True``: every tile is resized into a single cell (classic uniform grid).

        When the orientation is isometric, a ``<grid orientation="isometric" .../>``
        element is written so Tiled treats it as an isometric tileset.

        Returns:
            A :class:`TilesetExportResult`.
        """
        if self.grid.fit_to_cell:
            return self._export_uniform(out_path, write_tsx, write_tsj)
        return self._export_keep_size(out_path, write_tsx, write_tsj)

    def _grid_kwargs(self, cell_w: int, cell_h: int) -> dict:
        """Build the isometric <grid> kwargs for the definition writers."""
        if self.grid.orientation == "isometric":
            return dict(
                grid_orientation="isometric",
                grid_width=cell_w,
                grid_height=cell_h,
            )
        return {}

    def _export_uniform(self, out_path, write_tsx, write_tsj) -> "TilesetExportResult":
        """Classic uniform-grid export: one cell per tile."""
        cells = self.rendered_cells()
        cfg = self.grid.to_pack_config()
        result = export.export_tileset(
            cells,
            cfg,
            out_path,
            write_tsx=write_tsx,
            write_tsj=write_tsj,
            **self._grid_kwargs(self.grid.tile_width, self.grid.tile_height),
        )
        return TilesetExportResult(
            image_path=result.image_path,
            tsx_path=result.tsx_path,
            tsj_path=result.tsj_path,
            tile_count=result.tile_count,
            columns=result.columns,
            rows=result.rows,
            width=result.width,
            height=result.height,
        )

    def _export_keep_size(self, out_path, write_tsx, write_tsj) -> "TilesetExportResult":
        """Size-preserving export: large tiles span multiple cells (shelf packed)."""
        grid = self.grid
        cw, ch = grid.tile_width, grid.tile_height
        placements, cols_cells, rows_cells = self.shelf_layout()

        width = max(cw, cols_cells * cw)
        height = max(ch, rows_cells * ch)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        if grid.background is not None:
            base = Image.new("RGBA", (width, height), tuple(grid.background))
            base.alpha_composite(canvas)
            canvas = base
        for img, col, row, off_x, off_y in placements:
            canvas.alpha_composite(img, (int(col * cw + off_x), int(row * ch + off_y)))

        out_path = os.fspath(out_path)
        if os.path.splitext(out_path)[1] == "":
            out_path = out_path + ".png"
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        canvas.save(out_path, "PNG")

        tile_count = cols_cells * rows_cells
        meta = dict(
            name=grid.name,
            image_source=os.path.basename(out_path),
            image_width=width,
            image_height=height,
            tile_width=cw,
            tile_height=ch,
            tile_count=tile_count,
            columns=cols_cells,
            **self._grid_kwargs(cw, ch),
        )
        stem = os.path.splitext(out_path)[0]
        tsx_path = tsj_path = None
        if write_tsx:
            tsx_path = stem + ".tsx"
            tiled.write_tsx(tsx_path, **meta)
        if write_tsj:
            tsj_path = stem + ".tsj"
            tiled.write_tsj(tsj_path, **meta)

        return TilesetExportResult(
            image_path=out_path,
            tsx_path=tsx_path,
            tsj_path=tsj_path,
            tile_count=tile_count,
            columns=cols_cells,
            rows=rows_cells,
            width=width,
            height=height,
        )
