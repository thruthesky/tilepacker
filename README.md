# tilepacker

A Python package that packs individual tile images into a **uniform-grid tileset for the Tiled map editor** (PNG + `.tsx`/`.tsj`).

It collects tile PNGs exported individually from tools like Aseprite, merges them into a single uniform-grid sheet, and also generates the matching Tiled `.tsx`/`.tsj` definition files. Because the output is a standard grid tileset where every cell is the same size, you can use it directly in engines like **Flame / flame_tiled** without any custom loader.

> A typical "texture atlas" packer rotates/trims tiles and gives them varying cell sizes, which breaks Tiled's uniform-grid assumption. tilepacker deliberately lays tiles out on a **fixed grid** only, so you can point a `.tsx` straight at the resulting sheet.

---

## Features

- **Individual tile packing** — composite multiple PNGs into a single uniform-grid tileset
- **Grid slicing** — cut an existing spritesheet into a grid to split it back into individual tiles, or repack it
- **Five resize modes** — `none` / `stretch` / `fit` / `cover` / `crop`
- **Background removal** — global color matching or corner flood fill, with a color-distance tolerance
- **Trim** — automatically strip transparent borders per tile
- **extrude (preventTearing)** — expand each tile's edges outward to prevent neighboring-tile bleeding when scaling
- **margin / spacing** — set the outer tileset margin and the gap between tiles
- **Column count (columns)** — `0` lays tiles out close to a square automatically
- **Duplicate/empty tile removal** — drop pixel-identical duplicate tiles and fully transparent tiles
- **Sort** — `none` / `name` / `natural` (tile2 < tile10)
- **Tiled definition output** — generates `.tsx` (XML) by default, with optional `.tsj` (JSON)
- **CLI + GUI** — a command-line subcommand interface plus a **PySide6 desktop GUI** (drag & drop import, per-tile editing, isometric diamond crop, and choosing which tiles go into the tileset)

All images are processed in Pillow RGBA mode. numpy is an **optional accelerator**; even without it installed, a pure-Pillow fallback produces identical results.

---

## Installation

Clone the repository and install the dependencies in a virtual environment.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Alternatively, installing it as a package registers the `tilepacker` console command.

```bash
.venv/bin/pip install -e .
```

numpy is optional (it accelerates background removal and duplicate detection). If you want the acceleration, install it together via the `fast` extra.

```bash
.venv/bin/pip install -e ".[fast]"
```

- Required: **Pillow** (`>=10.0.0`)
- Optional: **numpy** (`>=1.24.0`) — without it, the pure-Pillow path is used automatically
- The GUI (`tilepacker gui`) requires **PySide6** (installed automatically with the package via `pip install -e .`, or `pip install PySide6`).

---

## Quick Start

First, generate sample tiles with the example script.

```bash
.venv/bin/python examples/generate_sample_tiles.py
```

Pack the generated individual tiles into a single 16x16 tileset.

```bash
.venv/bin/python -m tilepacker pack "out/tiles/*.png" \
    -o out/terrain.png \
    --tile-width 16 --tile-height 16 \
    --name terrain
```

The command above produces `out/terrain.png` (a uniform-grid tileset) along with a matching `out/terrain.tsx` definition file. (If you installed the `tilepacker` console command, you can use `tilepacker` instead of `python -m tilepacker`.)

---

## CLI Reference

The entry point is `python -m tilepacker <command>` (or `tilepacker <command>` when installed), and the subcommands are `pack` / `slice` / `resize` / `rmbg` / `info` / `gui`. The exit code is `0` on success and `1` on failure.

### `pack` — pack individual tiles into a tileset

```bash
python -m tilepacker pack INPUTS... -o OUTPUT.png [options]
```

| Option | Default | Description |
| --- | --- | --- |
| `INPUTS...` | (required) | Tile image files or glob patterns (one or more) |
| `-o`, `--output` | (required) | Output tileset PNG path |
| `-tw`, `--tile-width` | `32` | Tile cell width (px) |
| `-th`, `--tile-height` | `32` | Tile cell height (px) |
| `-c`, `--columns` | `0` | Tileset column count. `0` means auto |
| `--margin` | `0` | Outer tileset border margin (px) |
| `--spacing` | `0` | Gap between tiles (px) |
| `--extrude` | `0` | Expand each tile's edges outward (px), preventTearing |
| `--resize-mode` | `fit` | `none` / `stretch` / `fit` / `cover` / `crop` |
| `--resample` | `nearest` | `nearest` / `box` / `bilinear` / `hamming` / `bicubic` / `lanczos` |
| `--pad-color` | (transparent) | Padding fill color for `fit` mode (`#rrggbb`, `r,g,b,a`, `none`, etc.) |
| `--background` | (transparent) | Base background color for each cell |
| `--remove-bg` | off | Enable background removal |
| `--bg-color` | (auto) | Background color to remove. If unset, the four corners are sampled automatically |
| `--bg-tolerance` | `0` | Background color-distance tolerance (`0..441`) |
| `--bg-flood` | off | Remove the background via corner flood fill |
| `--trim` | off | Automatically strip transparent borders per tile |
| `--sort` | `none` | `none` / `name` / `natural` |
| `--dedup` | off | Remove pixel-identical duplicate tiles |
| `--drop-empty` | off | Remove fully transparent tiles |
| `--name` | `tileset` | Tileset name (the `name` attribute of `.tsx`) |
| `--tsx` / `--no-tsx` | generated | Whether to generate the `.tsx` definition file (`--no-tsx` disables it) |
| `--tsj` | off | Also generate a `.tsj` (JSON) definition file |

Example:

```bash
python -m tilepacker pack "tiles/*.png" -o out/town.png \
    -tw 32 -th 32 -c 8 --extrude 1 \
    --remove-bg --bg-color "#ff00ff" --bg-tolerance 16 \
    --trim --dedup --drop-empty --sort natural --tsj
```

### `slice` — slice or repack a spritesheet

The default mode cuts the sheet into a grid and saves individual PNGs (`tile_0000.png` …). Passing `--repack` recomposites the cut tiles back into a tileset.

```bash
# Slice: split the sheet into individual tiles
python -m tilepacker slice sheet.png -o out/tiles -tw 16 -th 16

# Repack: slice, then composite back into a tileset (applies dedup/extrude/column relayout)
python -m tilepacker slice sheet.png --repack --output out/repacked.png \
    -tw 16 -th 16 -c 8 --extrude 1 --drop-empty
```

| Option | Default | Description |
| --- | --- | --- |
| `SHEET` | (required) | Input spritesheet image path |
| `-o`, `--output-dir` | — | Directory to save the cut tiles into (default mode) |
| `--output` | — | Output tileset PNG path when repacking (`--repack`) |
| `-tw`, `--tile-width` | `32` | Cell width (px) |
| `-th`, `--tile-height` | `32` | Cell height (px) |
| `--margin` | `0` | Outer border margin of the input sheet (px) |
| `--spacing` | `0` | Gap between cells in the input sheet (px) |
| `--sheet-offset` | `0,0` | Start offset `x,y` of the input sheet |
| `-c`, `--columns` | `0` | Tileset column count when repacking. `0` means auto |
| `--extrude` | `0` | Expand each tile's edges when repacking (px) |
| `--name` | `tileset` | Tileset name when repacking |
| `--drop-empty` | off | Exclude fully transparent tiles |
| `--repack` | off | Composite the cut tiles back into a tileset |
| `--tsx` / `--no-tsx` | generated | Whether to generate `.tsx` when repacking |
| `--tsj` | off | Also generate `.tsj` when repacking |

### `resize` — resize multiple images to a given cell size

```bash
python -m tilepacker resize INPUTS... -o OUTPUT_DIR [options]
```

| Option | Default | Description |
| --- | --- | --- |
| `INPUTS...` | (required) | Input image files or glob patterns (one or more) |
| `-o`, `--output-dir` | (required) | Directory to save the results into |
| `-tw`, `--tile-width` | `32` | Target width (px) |
| `-th`, `--tile-height` | `32` | Target height (px) |
| `--resize-mode` | `fit` | `none` / `stretch` / `fit` / `cover` / `crop` |
| `--resample` | `nearest` | `nearest` / `box` / `bilinear` / `hamming` / `bicubic` / `lanczos` |
| `--pad-color` | (transparent) | Padding fill color for `fit` mode |

### `rmbg` — remove the background from multiple images

```bash
python -m tilepacker rmbg INPUTS... -o OUTPUT_DIR [options]
```

| Option | Default | Description |
| --- | --- | --- |
| `INPUTS...` | (required) | Input image files or glob patterns (one or more) |
| `-o`, `--output-dir` | (required) | Directory to save the results into |
| `--bg-color` | (auto) | Background color to remove. If unset, the four corners are sampled automatically |
| `--bg-tolerance` | `0` | Background color-distance tolerance (`0..441`) |
| `--bg-flood` | off | Remove the background via corner flood fill |

### `info` — print image/tileset sizes and inferred grids

```bash
python -m tilepacker info PATHS...
```

Prints each image's size and mode, plus the uniform-grid candidates (`cols x rows`) that exactly fit common tile sizes (8/16/24/32/48/64/96/128).

### `gui` — desktop GUI

```bash
python -m tilepacker gui      # or: tilepacker gui  /  tilepacker-gui
```

A PySide6 desktop app for building an isometric (or orthogonal) tileset visually. Layout: **Edit Tile** (left) │ **Tileset Preview** (right) │ **settings** (far right). Requires PySide6.

Workflow:

1. **Import** images by dragging them onto the window (or the *Add* button). Imported images are *sources* only.
2. **Edit** the selected source in the canvas: drag inside to **crop**, drag a corner to **resize**, press **`S`** to crop to the cell-ratio **diamond**, or **right-click** a thumbnail for quick actions (diamond / remove background / trim / reset / delete).
3. Adjust hue / saturation / brightness / contrast and the grid (`Tile width`/`height`, `Columns`, …) in the settings panel.
4. Click **`Add → Tileset`** to put the (edited) tile into the Tileset Preview — only tiles marked with `✓` are exported. The Tileset Preview is a `Columns`-wide grid that matches the exported sheet.
5. **Export Tileset** writes the PNG plus `.tsx`/`.tsj`. (Export is blocked while the tileset is empty.)

**Grid Split** — to pick individual cells out of a sheet, set the `Split:` `W × H` size (independent of the export grid) and toggle **`⊞ Split Grid`**: a cell grid is overlaid on the source. **Left-clicking a cell adds just that one cell** to the tileset (not the whole source); click more cells to keep adding. To place a cell at a specific position, **right-click a cell → "Copy this cell"**, then **right-click the Tileset Preview → "Paste copied cell here"** (or `Cmd/Ctrl+V` to append). Each cell keeps the source path plus that cell's crop, so it survives a workspace save/reload. While Split is on, the canvas right-click menu acts on the cell (Add/Copy this cell) instead of the whole tile.

### `gui2` — minimal isometric GUI

```bash
python -m tilepacker gui2     # or: tilepacker gui2  /  tilepacker-gui2  /  ./gui.sh
```

A stripped-down, **isometric-only** app for the core workflow: cut diamond cells
out of a source image and lay them out into an isometric tileset. Layout:
**Tile Editor** (left) │ **Tileset Preview** (right).

Workflow:

1. **Add image** — pick one or more source images (shown in the image list). You
   can also **drag image files onto the editor**, or **paste an image from the
   clipboard** (*Paste image* button / `Cmd/Ctrl+Shift+V`).
2. **Split Grid** — set the cell `W × H` and click *Split Grid* to overlay the
   isometric diamond grid on the selected image.
3. **Select** cells — drag to select an area (choose **Diamond** or **Rect**
   shape in the `Select:` box), click a single cell, or **Shift+click / Shift+drag**
   to add more cells to the selection.
4. **Copy** the selection (**`Cmd/Ctrl+C`** or the *Copy* button), or **drag the
   selection straight onto the preview**.
5. **Paste** into the preview (**`Cmd/Ctrl+V`** or the *Paste* button). Click a
   preview cell first to paste at that **anchor** (drops one cell onto one cell);
   with no anchor it pastes at the origin. The preview reproduces the **exact
   diamond shape** you selected.
6. Preview editing: **click** a cell to select it, **Delete** it (*Delete cell*
   button or Delete/Backspace), **Undo** (**`Cmd/Ctrl+Z`** or *Undo*), or *Clear*.
7. **Export** — writes three files next to each other:
   - `<name>.png` — the packed tile image.
   - `<name>.tsx` — the tile **palette** (a plain square grid, so each tile is
     easy to tell apart and pick in Tiled's tileset view).
   - `<name>.tmx` — the **isometric map** holding your exact layout.

> ⚠️ **Open the `<name>.tmx` in Tiled to see the layout exactly as in the
> Tileset Preview.** The `.tsx` is only the tile *palette* (a list of tiles), not
> the arrangement — opening it shows the tiles in a square grid, not your map. To
> reproduce the preview's isometric layout, **open the `.tmx` map** (it references
> the `.tsx`/`.png`, so keep all three in the same folder).

**Import / Save workspace** — *Save workspace* stores the whole session (source
list, grid size, collected tiles) as a `.json`; *Import* loads it back.

---

## Python API

You can also call it directly from code without the CLI. The core entry points are `PackConfig` and `pack_from_files`.

```python
from tilepacker import PackConfig, pack_from_files

cfg = PackConfig(
    tile_width=16,
    tile_height=16,
    columns=8,
    extrude=1,          # preventTearing
    resize_mode="fit",
    bg_remove=True,
    bg_tolerance=16,
    trim=True,
    deduplicate=True,
    drop_empty=True,
    sort="natural",
    name="terrain",
)

result = pack_from_files(
    ["a.png", "b.png", "c.png"],
    cfg,
    "out/terrain.png",
    write_tsx=True,    # also generate out/terrain.tsx
    write_tsj=False,   # if True, also generate out/terrain.tsj
)

print(result.image_path)   # out/terrain.png
print(result.tsx_path)     # out/terrain.tsx
print(result.tile_count, result.columns, result.rows)
print(result.width, result.height)
```

To repack directly from a spritesheet, use `pack_from_spritesheet`.

```python
from tilepacker import PackConfig, pack_from_spritesheet

cfg = PackConfig(tile_width=16, tile_height=16, columns=8, extrude=1)
result = pack_from_spritesheet(
    "sheet.png",
    cfg,
    "out/repacked.png",
    sheet_margin=0,
    sheet_spacing=0,
    sheet_offset=(0, 0),
    write_tsx=True,
)
```

In addition, `export_tileset`, `pack_tiles`, `PackedTileset`, `resize_image`, `remove_background`, `trim`, `extrude_edges`, `load_image`, `slice_image`, `slice_sheet`, `deduplicate`, `parse_color`, `ExportResult`, and more are importable from the package top level.

---

## Using it in Tiled

Keep the generated `.tsx` and PNG in the same folder, then in Tiled open the `.tsx` via **File > Open** (or, while editing a map, the + button in the **Tilesets** panel > **Open Tileset**) to add it as a tileset. Because the `image source` in the `.tsx` points to the PNG's filename (a relative path), the two files must live in the same directory. In Flame/flame_tiled, just reference this PNG/`.tsx` directly as map assets.

**Isometric layout from `gui2`:** the `gui2` app also exports a `<name>.tmx` map
alongside the `.tsx`/PNG. **Open the `.tmx` in Tiled** (File > Open) to see your
tiles laid out exactly as in the Tileset Preview — the `.tsx` on its own is just
the tile palette (a square grid of tiles), not the arrangement. Keep the `.tmx`,
`.tsx`, and PNG together so the map can find its tileset and image.

---

## License

MIT License.
