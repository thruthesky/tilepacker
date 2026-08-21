# tilepacker — Project Guide (SSOT)

`tilepacker` is a Python tool that packs individual tile images into a **uniform-grid
tileset** (PNG + `.tsx`/`.tsj`) for the [Tiled](https://www.mapeditor.org/) map editor.
The generated `.tsx` can be pointed at directly from Tiled or `flame_tiled` — no custom
loader needed.

This file is the **single source of truth (SSOT)** for project-wide conventions.

---

## Display Language Policy (SSOT — MUST FOLLOW)

**All user-facing display text in this project MUST be written in English.** This is the
authoritative language convention for the project and overrides any other default.

"Display text" includes, without exception:

- Docstrings and code comments
- CLI output: messages, errors, `argparse` help / description / metavar
- GUI labels, buttons, dialogs, message boxes
- `README.md` and all documentation (including this file)
- Exception messages and log messages
- Example scripts and shell scripts

**Do NOT translate (keep verbatim):** identifiers (variable / function / class / module
names), keyword-argument names, dict & JSON keys, string constants used as *values*
(e.g. `"tileset"`, `"RGBA"`, `"PNG"`, resize modes `"fit"`/`"none"`/`"stretch"`/`"cover"`/`"crop"`,
resample names, sort modes `"none"`/`"name"`/`"natural"`), file paths, `import` statements,
and format-string substitution fields.

When you add or edit any file, write every human-readable string in English. After
changes, verify that no non-English natural language remains in display text:

```bash
grep -rlP '[가-힣]' tilepacker tests examples README.md   # must print nothing
```

---

## Architecture

```
tilepacker/
├── tilepacker/
│   ├── core/
│   │   ├── config.py     # PackConfig — the shared settings contract for every module
│   │   ├── imageops.py   # resize / remove background / trim / extrude (Pillow, numpy-accelerated)
│   │   ├── slicer.py     # cut a spritesheet into a grid of tiles
│   │   ├── packer.py     # compose tiles into a uniform-grid tileset image
│   │   ├── dedup.py      # remove duplicate / empty tiles
│   │   ├── tiled.py      # build Tiled .tsx (XML) / .tsj (JSON) definitions
│   │   └── export.py     # pipeline orchestration: input → preprocess → pack → save
│   ├── cli.py            # argparse CLI: pack / slice / resize / rmbg / info / gui / gui2
│   ├── gui_app/          # full PySide6 GUI      -- `tilepacker gui`
│   ├── gui2/             # minimal isometric GUI -- `tilepacker gui2`, what ./gui.sh runs
│   │   ├── isogrid.py    # diamond-cell maths + the diamond cut (Qt-free, unit tested)
│   │   ├── editor.py     # left panel: source image + drag-select cells
│   │   ├── tileset.py    # right panel: isometric tileset preview
│   │   ├── state.py      # shared state: sources, grid, clipboard, workspace
│   │   └── app.py        # window, Import / Export / Save workspace
│   └── __main__.py       # `python -m tilepacker`
├── tests/                # pytest suite (279 tests, including regression tests)
├── examples/             # generate_sample_tiles.py + demo.sh
└── pyproject.toml        # packaging; `tilepacker` console script entry point
```

Design rules:

- All images are handled in Pillow **RGBA** mode.
- `numpy` is an *optional* accelerator; every module falls back to pure Pillow when it is
  absent and must produce identical results.
- `PackConfig` (in `core/config.py`) is the single contract shared by all core modules.
- `extrude` (preventTearing) widens each tile's edge band; `export` records the
  **extrude-corrected** `margin`/`spacing` into the `.tsx`/`.tsj` so Tiled slices correctly
  (`tsx_margin = margin + extrude`, `tsx_spacing = spacing + 2*extrude`).

---

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -e .          # installs Pillow and the `tilepacker` console script
.venv/bin/pip install -e ".[fast]"  # optional: add numpy for acceleration
```

Both GUIs use **PySide6**, which `pip install -e .` already pulls in as a
required dependency -- there is nothing extra to install.

---

## Usage

```bash
# Pack loose tiles into a tileset (PNG + .tsx), 8 columns:
tilepacker pack tiles/*.png -o out/terrain.png -tw 32 -th 32 -c 8

# Pack with background removal, extrude (anti-bleed), and a .tsj too:
tilepacker pack tiles/*.png -o out/terrain.png -tw 32 -th 32 \
    --remove-bg --bg-color "#ff00ff" --extrude 2 --dedup --tsj

# Slice a spritesheet into individual tiles:
tilepacker slice sheet.png -tw 16 -th 16 -o out/tiles

# Slice and re-pack into a clean, deduplicated tileset:
tilepacker slice sheet.png -tw 16 -th 16 --repack --output out/clean.png --dedup

# Resize / remove background in batch:
tilepacker resize tiles/*.png -o out/resized -tw 16 -th 16 --resize-mode fit
tilepacker rmbg tiles/*.png -o out/nobg --bg-color "#ff00ff"

# Inspect an image and estimate its grid:
tilepacker info sheet.png

# Launch the full GUI:
tilepacker gui

# Launch the minimal isometric GUI (what ./gui.sh runs):
tilepacker gui2
```

Python API:

```python
from tilepacker import PackConfig, pack_from_files

cfg = PackConfig(tile_width=32, tile_height=32, columns=8, extrude=2, deduplicate=True)
result = pack_from_files(["a.png", "b.png", "c.png"], cfg, "out/tileset.png", write_tsj=True)
print(result.image_path, result.tsx_path, result.tile_count)
```

Run the test suite:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests -q
```

---

## Background / Origin

The project originated from a survey of existing grid-tileset packers for Tiled. Key
context that shaped the design:

Tiled's standard image-based tileset expects a **uniform grid** (every tile the same cell
size, optional margin/spacing). So this is a packer that lays tiles out on a fixed grid,
not a tight "texture atlas" packer that rotates/trims/varies sizes — atlases of the latter
kind won't load as a normal Tiled tileset.

Reference tools that informed the feature set:

- **mini2dx/tilepacker** — a Gradle/CLI utility for packing tile images into tilesets with
  `tileWidth`/`tileHeight`, tileset dimensions, tile padding, and a "preventTearing" option
  that pads each tile by its border pixels to avoid bleeding when scaling. (This project's
  `--extrude` mirrors that idea.)
- **TilePacker (craftworkgames)** — a minimal .NET tool that packs a directory of PNGs into
  one texture, each cell sized to the largest input.
- **TileFusion (itch.io)** — a simple GUI to combine tiles and export a single PNG.
- **Tilesetter** — a tileset *generator* with auto-tiling (edges/corners), beyond pure packing.
- **TexturePacker / tiny_packer / ImageMagick montage** — texture-atlas / montage routes;
  only the uniform-grid (`--unified`, `montage -tile`) modes are compatible with Tiled's grid
  assumption.

This project follows the grid-packer approach so the output drops straight into a `.tsx`
for Tiled / `flame_tiled` with no custom loader.
