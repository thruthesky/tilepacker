# tilepacker GUI Improvement Plan (v3 — consolidated)

**Status:** Planning / hand-off document (no code changes in this doc)
**Audience:** The team taking over the GUI work
**Basis:** `tilepacker/gui_app/` (PySide6, ~4,800 LOC), current `main` branch
**Language (SSOT):** Every **display string in the codebase** (menus, buttons,
labels, docstrings, comments, errors) **must be English** — see
[CLAUDE.md](../CLAUDE.md). This planning doc is also kept in English so the whole
`docs/` tree stays consistent. Verify after any change:
```bash
grep -rlP '[가-힣]' tilepacker tests examples README.md   # must print nothing
```

> **v3 note — why this doc replaces two earlier ones.** Two plans had grown in
> parallel (`IMPROVEMENT_PLAN.md` = backlog + critique; `gui-improvement-plan.md`
> = screen diagnosis + personas + wireframe + a 50-item catalog). Keeping both
> guarantees drift. v3 **merges** them: it keeps the prioritized, testable
> backlog **and** adds the per-screen diagnosis, persona journeys, wireframe and
> the expanded feature catalog — then runs a **critical review (§6)** over the
> combined proposals so the receiving team doesn't build the wrong things.
> `IMPROVEMENT_PLAN.md` has been removed; this is the single source of truth.

---

## 1. At a glance

| Section | Content |
|---|---|
| **§2 Already done** | What ships today — **do not rebuild**, only extend |
| **§3 Per-screen diagnosis** | Concrete pain points: left / center / right / top |
| **§4 Persona journeys** | Where a beginner and a power user get stuck |
| **§5 Proposed layout** | Wireframe + a low-cost alternative |
| **§6 Critical review** | What to **change or defer** in the proposals (read this) |
| **§7 Prioritized backlog** | P0 / P1 / P2 with files, acceptance, tests, effort, risk |
| **§8 Feature catalog** | 50+ ideas by category with difficulty (a menu, not a TODO) |
| **§9 Roadmap** | Milestones M1–M6 |
| **§10–12** | Engineering rules, QA checklist, open product questions |

---

## 2. Already implemented (⚠️ do not rebuild — extend only)

| Area | Shipped | Where |
|---|---|---|
| Menus | File · Edit · Tile · Tileset · Help | `main_window._build_actions` |
| Workflow | 4-step bar `① Import → ② Edit → ③ Add to Tileset → ④ Export` | `_build_step_bar` / `_update_steps` |
| Edit toolbar | Diamond · 90°↺↻ · Flip H/V · Remove BG · Trim · Grayscale · Reset | `_build_tool_row` |
| Preview | Zoom (wheel/buttons) · pan · Fit · output summary · click-select · drag reorder · align | `preview_canvas.py` |
| **Preview ↔ Edit link** | Click a preview tile → selects it in Edit; selecting an in-tileset tile highlights its preview cell | `main_window`, `preview_canvas` |
| Right panels | Grid + Tile **collapsible Advanced**, size/span label | `panels.py`, `edit_size_label` |
| **Clean up** | Remove duplicates · drop empty · sort (none/name/natural) | `model.deduplicate/drop_empty/sort_tiles`, `Tileset ▸ Clean Up` |
| **Folder import** | Recursive, extension-filtered | `main_window.import_folder` (`Ctrl+Shift+I`) |
| Core | undo/redo (coalesce), workspace `.json`, diamond mask, copy/paste, drag&drop import, right-click menu, empty-tileset export guard | `model.py`, `main_window.py` |

> The cleanup actions, folder import, preview zoom/pan and the two-way
> Preview↔Edit link landed **after** the first drafts of both plans, so several
> items those drafts listed as "to do" are already done. This table is current.

---

## 3. Per-screen diagnosis (current pain points)

Layout today: **left (Edit) · center (Preview) · right (Settings)** + a top
band (menu / toolbar / step bar).

### 3-1. Left — Edit Tile
- ✅ Buttons, toolbar and hints are well stocked.
- ❌ **Tile list is a single horizontal strip** → long horizontal scrolling once
  there are many tiles; single-selection only.
- ❌ **Canvas shows the raw image** (e.g. a magenta background) → a beginner asks
  "why does it look like that?" before background removal.
- ❌ **No isometric cell guide** → diamond alignment is done by eye.
- ❌ **Two overlapping hint texts** (label above the canvas + `_paint_hint`).

### 3-2. Center — Tileset Preview
- ✅ Zoom/pan/Fit, output summary, reorder, selection highlight.
- ❌ **Isometric tiles are laid out on square cells** (`fit_to_cell` off → shelf);
  a diamond projection is not the default for iso.
- ❌ When only a few tiles are `in_tileset`, the rest are invisible here → "why do
  I see 3 of my 8 tiles?" (the source-vs-tileset rule isn't obvious).

### 3-3. Right — Grid / Tile Adjustments
- ✅ Collapsible Advanced, clear size label.
- ❌ No grid **presets** (set up by hand every time); terms (Margin/Spacing/
  Extrude) lack inline explanation.
- ❌ Large empty space when no tile is selected.

### 3-4. Top — menu / toolbar / step bar
- ✅ Five menus + step bar + toolbar.
- ❌ Import is reachable three ways (menu, toolbar, Add button) — some redundancy.
- ❌ Help only has Shortcuts (no Quick Start / About).

---

## 4. Persona journeys (where they get stuck)

### 👶 "Newbie" — total beginner making one isometric tileset from 8 images
| Step | Sticking point | Fix (§) |
|---|---|---|
| Start | Blank window — what do I click? | 7-P0-1 onboarding |
| After import | Preview looks empty (sources only) | 7-P0-2 in_tileset clarity |
| Editing | What is "Diamond"? why the magenta? | 7-P1-2 iso guide, 7-P1-3 bg auto-detect |
| Export | "No tiles" because nothing was added | 7-P0-2 |

### 🎮 "Indie" — handles hundreds of tiles, iterates fast
| Step | Sticking point | Fix (§) |
|---|---|---|
| Import | One file at a time | ✅ folder import (done); 7-P1-5 spritesheet wizard |
| Organize | No search/sort/tags; horizontal scroll | 7-P0-3 list+search/filter |
| Editing | No bulk edit, no precise zoom | 7-P0-4 batch, 7-P1-1 editor zoom |
| Export | Re-enters settings every time | 7-P0-6 export dialog, 7-P1-4 presets/recents |

---

## 5. Proposed layout (wireframe)

Key change: move the tile list to a **vertical, wrapping, multi-select panel**
with search; editing stays center; settings stay right.

```
┌─ Menu: File Edit Tile Tileset View Help ─────────────────────────────┐
│ Steps: ① Import → ② Edit → ③ Add to Tileset → ④ Export   [Quick Start]│
├──────────┬───────────────────────────────┬──────────────────────────┤
│ Tiles    │  Edit Tile                    │  Grid / Tileset          │
│ [🔍search]│  [toolbar: ◇ ↺ ↻ ⇆ ⇅ BG Trim] │  Preset ▾  Iso 64×32     │
│ □ tile00 │  ┌─────────────────────────┐  │  Orientation / W / H     │
│ ✓ tile01 │  │ (canvas + iso cell guide)│  │  ▸ Advanced              │
│ ✓ tile02 │  │                         │  │  ───────────             │
│ □ tile03 │  └─────────────────────────┘  │  Tile Adjustments        │
│ □ tile04 │  Source 64² · spans 1×2       │  Size / Rotation / Flip  │
│ …(vertical│ ─────────────────────────────│  ▸ Advanced (color/bg)   │
│  wrap,    │  Tileset Preview (iso diamond)│                          │
│  multi-   │  [− Fit +]  Output 192×96     │                          │
│  select)  │  ◇◇◇ …                        │                          │
│ [Add▸TS]  │                               │                          │
├──────────┴───────────────────────────────┴──────────────────────────┤
│ Status: Tiles 8 (3 in tileset) · Grid iso 64×32 · Output 192×96       │
└──────────────────────────────────────────────────────────────────────┘
```

> **Low-cost alternative (recommended first):** keep the current 3-pane split,
> just make the tile list vertical/wrapping + add a search box. Big gain, small
> change, low regression risk. Do the full re-layout only if it proves needed.

---

## 6. Critical review of the proposals (read before committing)

The combined catalog is ambitious; this section is the filter. Items here
**override** anything in §7/§8 they conflict with.

- **C1 — "Auto-add to tileset on import" must be opt-in, default OFF.**
  One earlier plan proposed setting `in_tileset=True` automatically on import.
  This **conflicts with an explicit standing user constraint** ("do not auto-add
  tiles to the preview; only what the user selects"). Resolve the beginner
  confusion with **empty-state guidance + a prominent "Add to Tileset" affordance
  + clear naming** (§7-P0-2). An auto-add toggle may exist but must default OFF
  and be remembered per-user.
- **C2 — Defer heavy infrastructure until a measured need.** Background worker
  (`QThread`/`QRunnable`), autosave + crash recovery, file "watch mode", and a
  plugin-hook system are **over-engineered for the current scale** (tens–hundreds
  of tiles) and add real regression risk in Qt. Keep the **render/thumbnail cache**
  (low risk, high value); defer the rest until profiling shows a need.
- **C3 — Trim the export presets.** A "Flame / flame_tiled" preset is redundant:
  `flame_tiled` consumes a standard `.tsx`. Keep a short, meaningful set:
  *Pixel-art safe*, *Isometric 64×32*, *PNG only*.
- **C4 — Cross-widget drag (source list → preview) is low ROI.** It is costly to
  implement/test and duplicates existing paths (click, "Add → Tileset" button,
  Cmd+V). Prefer **double-click to add**; postpone DnD-to-preview.
- **C5 — The 50+ catalog is a menu, not a backlog.** Only P0/P1 in §7 are
  committed work. §8 is an idea bank to pull from; do not treat it as a TODO list
  or scope will sprawl.
- **C6 — "Empty/Duplicate" list filters depend on detection logic.** That logic
  now exists in the model (`deduplicate`, `drop_empty` use `core/dedup`). Reuse
  it for the filters; don't reimplement.
- **C7 — Diamond-default preview for isometric is a behavior change.** Making the
  iso preview project as diamonds by default (instead of the size-preserving
  shelf) changes existing output expectations and tests. Gate it behind a clear
  toggle and add fixtures before flipping the default.

---

## 7. Prioritized backlog

Effort **S** ≈ ≤0.5d, **M** ≈ 1–2d, **L** ≈ 3d+. Each item: purpose · work ·
files · acceptance · tests · effort/risk.

### P0 — Highest-impact usability (do first)

#### P0-1 · First-run empty state + Quick Start — **S**
- **Purpose:** A blank window should tell you what to do.
- **Work:** When `len(tiles)==0`, show a centered empty state in the tile area
  with big **Import Images** / **Slice Spritesheet** buttons and "or drag images
  here"; highlight step ①. Add **Help → Quick Start** (1-page workflow), shown
  once on first run.
- **Files:** `main_window` (empty-state widget toggled on tile count),
  `_show_quick_start`.
- **Acceptance:** Empty project shows guidance; it disappears after import.
- **Tests:** `test_empty_state_visible_when_no_tiles`.
- **Risk:** Low.

#### P0-2 · Remove the source-vs-tileset confusion — **S–M**
- **Purpose:** Beginners don't realize imported tiles aren't exported until added.
- **Work:** Rename the panes for clarity (**"Source Library"** left, **"Tileset
  Output"** center). When the tileset is empty but sources exist, the preview
  placeholder reads "Select tiles and click **Add → Tileset**". Add an **opt-in**
  preference **"Add new imports to the tileset automatically" (default OFF**, per
  **C1**). Show a live count ("8 tiles · 3 in tileset") in the status bar.
- **Files:** `main_window` (titles, placeholder text, preference via `QSettings`),
  `preview_canvas` placeholder.
- **Acceptance:** After import the user either sees tiles in the preview (if the
  opt-in is on) or a clear next-action; the source/output distinction is legible.
- **Tests:** `test_empty_tileset_placeholder_guides`, `test_auto_add_optin_default_off`.
- **Risk:** Low–Med.

#### P0-3 · Tile list → vertical/wrap gallery + search + filter — **M**
- **Purpose:** A horizontal strip doesn't scale past ~10 tiles.
- **Work:** Make the list wrap (multi-row) with a vertical scrollbar (a **View ▸
  Strip/Grid** toggle is optional). Add a **search box** (filename) and **filters**
  (All / In Tileset / Source Only / Empty / Duplicate — reuse model detection per
  **C6**) and **sort** (Original / Name / Natural / Size / Included-first).
- **Files:** `main_window._build_ui` (list config + filter widgets),
  `_apply_tile_filter`; sort already in `model.sort_tiles`.
- **Acceptance:** 100 tiles browse without horizontal scrolling; search/filter
  hide non-matching items; counts update.
- **Tests:** `test_tile_filter_search_hides_items`, `test_filter_in_tileset_only`.
- **Risk:** Low–Med.

#### P0-4 · Multi-select + batch edits (single undo) — **M**
- **Purpose:** Editing is one-tile-at-a-time; bulk ops are painful.
- **Work:** `ExtendedSelection` on the list. With >1 selected, toolbar/Tile-menu
  actions (Remove BG, Trim, Grayscale, Flip, Rotate, Diamond, Reset) and
  Add/Remove-from-Tileset apply to **all selected** in **one** `commit()`. Add
  **Edit → Apply current edits to selected** (copy the active `TileEdit` onto the
  rest). The canvas keeps showing the primary selection.
- **Files:** `main_window` (`_current_tile` → `_selected_tiles`, dispatch in
  `_toggle_edit`/`_rotate`/`_set_in_tileset`/`_apply_quick_edit`).
- **Acceptance:** Select 3 → "Remove BG" sets it on all 3; one undo reverts all 3.
- **Tests:** `test_batch_toggle_applies_to_selection`, `test_batch_is_single_undo`.
- **Risk:** Med (broad selection plumbing — consider extracting a controller).

#### P0-5 · Spritesheet slice wizard — **M**
- **Purpose:** The "cut by grid" workflow (original brief) is CLI-only.
- **Work:** **File → Slice Spritesheet…** dialog: pick image; set tile w/h,
  margin, spacing, offset; live grid overlay + tile-count read-out; optional
  drop-empty. On confirm, run `core/slicer` and add tiles as new sources (not
  auto-added to the tileset, per C1). Needs `ProjectModel.add_images(list[PIL])`
  for sourceless tiles — decide workspace persistence (see §12).
- **Files:** new `gui_app/slice_dialog.py`; `main_window._on_slice_sheet`;
  `model.add_images`; reuse `core/slicer.py`.
- **Acceptance:** An N×M sheet yields N·M tiles; offset/margin/spacing honored;
  drop-empty removes blank cells.
- **Tests:** `test_slice_dialog_adds_tiles` (synthetic 2×2 sheet → 4 tiles).
- **Risk:** Med.

#### P0-6 · Consolidated Export dialog / preflight — **M**
- **Purpose:** Export settings are scattered; no confidence before clicking.
- **Work:** **File → Export Tileset…** dialog with output path, name, columns,
  .tsx/.tsj toggles, and a **live preflight summary**: dimensions, tile count,
  cols×rows, orientation, **empty-tile count, duplicate count, missing-source
  warnings, oversize warning**. Reuse `_update_preview_summary` math. Keep `Ctrl+E`
  quick-export with last settings. Post-export: "open output folder" / "copy path".
- **Files:** new `gui_app/export_dialog.py`; refactor `export_tileset` to take a
  settings object.
- **Acceptance:** Dialog reflects the grid; toggling .tsj updates the summary;
  exactly the listed files are written.
- **Tests:** extend `test_mainwindow_import_export_*`.
- **Risk:** Low–Med.

### P0-0 — Crop UX repair — ✅ Done (2026-07-02)

Promoted out of P1 after real use showed cropping a large source was the biggest
pain point. Shipped:

- **Editor zoom/pan/Fit + pixel grid** (was P1-1/P1-8): wheel-zoom at the cursor,
  middle-drag pan, Fit/−/+ buttons, zoom read-out, per-pixel grid when zoomed in.
- **Numeric crop inspector** (was P1-7): L/T/R/B source-margin spin boxes in Tile
  Adjustments; edits are *source-space* so they work even with rotation/trim
  applied, and land pixel-exactly where the mouse can't.
- **Bigger crop hit areas + hover feedback + dimming**: enlarged handle/edge
  click areas (WCAG target size), full-edge hover rails, corner hover highlight,
  and a dim shield behind rubber-band crops.

Still open for a follow-up: a dedicated **source-space crop-frame mode** (show the
un-cropped source with the crop as a draggable 8-handle frame), grid/diamond snap,
aspect-ratio lock, and a slice/split wizard with offset/margin/spacing.

### P0-1 — Isometric Area Select + block copy/paste — ✅ Done (2026-07-02)

The other big pain point: Grid Split only added one diamond cell per click, and
copy/paste was single-tile. Now, Tiled-style:

- **Area select** — drag on the source to select many diamond cells at once
  (selection is a cell-space rectangle → diamond cluster on screen). Teal fill +
  outline, "Add N selected" count. Shift adds, Cmd/Ctrl subtracts, Cmd/Ctrl+A
  selects all, Esc clears. **Enter / "Add selected"** adds them all in row-major
  order. A plain single click still adds one immediately (backward compatible).
- **Block copy/paste** — Cmd/Ctrl+C copies the selection as a *block*; Cmd/Ctrl+V
  pastes the whole block into the tileset in order. A single copy supersedes the
  block. SSOT for the mapping is the existing `_iso_cell_at` (screen→cell) /
  `_cell_box` (cell→screen) pair.

Follow-up: TileBlock **relative-position matrix** paste into a specific output
slot with a **ghost preview**; Magic-Wand / Select-Same smart selection; named
stamp slots.

### P1 — Rich features

| ID | Item | Notes | Effort |
|---|---|---|---|
| P1-1 | **Editor canvas zoom/pan** — ✅ Done (P0-0) | Ported the preview's wheel-zoom/pan/Fit + 100% + pixel grid to `editor_canvas` | M |
| P1-2 | **Isometric cell guide overlay** | Diamond guide at grid ratio, View toggle, optional snap-to-center; visualize cell span on the canvas | M |
| P1-3 | **Eyedropper bg + mask preview + auto-detect** | Sample bg color by clicking; preview removed region; on import, if 4 corners match, offer "Remove background?" | M |
| P1-4 | **Recents + presets** | Recent files/workspaces; grid presets (Iso 64×32 / 128×64 / Ortho 32×32); compressed export presets (per C3) | S–M |
| P1-5 | **Tile metadata for Tiled** | Per-tile `class`/`type`, custom properties, display name → `.tsx`/`.tsj` (`core/tiled.py`); add golden fixtures | L |
| P1-6 | **Unsaved/dirty state** | Title `*` marker, "save before close?" prompt, enable/disable undo/redo from `can_undo/can_redo` | S |
| P1-7 | **Precise/numeric editing** — ✅ crop done (P0-0) | Numeric L/T/R/B crop shipped; still open: aspect lock, "crop to tile ratio", in-panel align | M |
| P1-8 | **Zoom read-out + presets** — ✅ editor done (P0-0) | Editor zoom % + Fit + pixel grid shipped; still open: `Ctrl+=`/`-`/`0` shortcuts, preset zooms | S |
| P1-9 | **Resample choice** | Surface `RESAMPLE_FILTERS` for fit-to-cell exports, default nearest | S |
| P1-10 | **Missing-source relink** | When a workspace's tile path is gone, offer to relink/locate | M |

### P2 — Polish / deferred

| ID | Item | Decision |
|---|---|---|
| P2-1 | Render/thumbnail cache keyed by `(path, edit-hash, size)`; 200-tile stress test | Do (low risk) when perf is felt |
| P2-2 | Theme (dark/light), font size / high-contrast, panel docking, shortcut rebinding | Nice-to-have |
| P2-3 | "Open in Tiled" after export | S, nice-to-have |
| P2-4 | Background worker (QThread), autosave + crash recovery, watch mode, plugin hooks | **Deferred** (per C2) |
| P2-5 | Animation frames, collision polygons | **Deferred** (large; after P1-5 metadata) |
| P2-6 | Auto-tiling, palette extraction/replace, multi-tileset/layers | **Phase-3 differentiation** (separate initiative) |

---

## 8. Feature catalog (idea bank — not a TODO; see C5)

Difficulty `S/M/L`. Pull from here into §7 when prioritized.

**A. Input/import:** folder import ✅(S) · spritesheet slice (M) · recent
files/workspaces (S) · paste image from clipboard (M).

**B. Tile management:** search/filter (S) · sort name/size/added/included (S) ·
display rename (S) · color tags / groups (M) · remove duplicate/empty ✅(S) ·
multi-select batch (M).

**C. Editing:** editor zoom/pan (M) · pixel-grid overlay (S) · color
replace/palette picker (M) · brightness/contrast/gamma curve (M) · outline/drop
shadow (M) · "apply this edit to all" preset (M).

**D. Isometric:** diamond preview default for iso (M, see C7) · cell snap/align
(M) · height/depth offset for walls (L) · staggered/diamond map preview (L).

**E. Grid/output:** grid presets (S) · visualize extrude/margin/spacing (M) ·
power-of-two output (S) · export presets (S, see C3) · multi-format export ✅partial(S).

**F. Tiled depth:** tile properties (L) · collision polygons (L) · animation
frames (L).

**G. Workflow/view/a11y:** autosave/backup (S, deferred C2) · undo-history panel
(M) · theme (M) · font size/high-contrast (M) · shortcut rebinding (M) · panel
docking/hide (M) · watch mode (L, deferred) · "Open in Tiled" (S).

---

## 9. Roadmap / milestones

| Milestone | Includes | Impact |
|---|---|---|
| **M1 First-run polish** | P0-1, P0-2, P0-6 | ★★★ |
| **M2 Handling many tiles** | P0-3, P0-4 | ★★★ |
| **M3 No more CLI detours** | P0-5 (slice), + grid/export presets (P1-4) | ★★ |
| **M4 Iso quality** | P1-1 (editor zoom), P1-2 (guide), P1-8 | ★★ |
| **M5 Confident projects** | P1-3 (eyedropper), P1-6 (dirty), P1-10 (relink) | ★ |
| **M6 Tiled depth** | P1-5 (metadata), then deferred P2-5 | ★ |

> Recommended start: **M1** (mostly `S`, biggest beginner payoff) → **M2**.
> Each milestone ends green: full `pytest` at exit 0 + the Korean-text grep clean.

---

## 10. Engineering guidelines (required)

```
gui_app/  app.py · main_window.py (assembly) · model.py (SSOT, Qt-free)
          editor_canvas.py · preview_canvas.py · panels.py · imageedit.py · qtutil.py
```
1. **Model is the SSOT.** All state/edit/render/export lives in `model.py`. A new
   state field must be reflected in `TileEdit`/`GridSettings`/`TileItem` **and**
   `to_dict`/`from_dict` (workspace) **and** `clone` (undo).
2. **Undo pattern.** Mutating slots call `self.model.commit()` after the change
   (continuous gestures use `commit(coalesce="key")`). Batch ops = one commit.
3. **English display text** (see header) — keep the grep clean.
4. **Headless-constructible & tested.** Widgets build under
   `QT_QPA_PLATFORM=offscreen`; pure logic → `tests/test_gui_core.py`, widgets →
   `tests/test_gui_app.py`.
5. **numpy is an optional accelerator** — pure-Pillow fallback must match.
6. **Non-destructive edits** — never mutate `TileItem.source`.
7. **`main_window.py` is large (~1.4k lines).** Before M2's batch work, consider
   extracting a small selection/dispatch controller as a pure, test-green refactor.

---

## 11. QA checklist (per change)

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests -q   # exit 0
grep -rlP '[가-힣]' tilepacker tests examples README.md                      # prints nothing
```
- Headless test for every new dialog/action (build offscreen, drive it, assert on `ProjectModel`).
- `.tsx`/`.tsj` writers: assert by parsing XML/JSON, incl. the extrude-corrected
  `margin`/`spacing` invariant (`tsx_margin = margin + extrude`,
  `tsx_spacing = spacing + 2*extrude`).
- Verify undo/redo for every mutating action (one gesture = one undo).
- Manual smoke before each milestone: import → slice → edit → add → export on a
  mixed set of large/small PNGs. Optional `win.grab().save(...)` screenshot diff.

---

## 12. Open questions for product

1. **Slice (P0-5):** add sliced tiles as new sources (proposed) or replace the
   project? Remember the sheet path for re-slicing?
2. **Sourceless tiles** (sliced/pasted) in workspace `.json`: embed pixels, or
   write a sidecar PNG cache folder?
3. **Batch (P0-4):** should color **sliders** (hue/brightness…) batch-apply live,
   or only discrete toggles/actions?
4. **Auto-add on import (C1):** confirm default OFF and whether the preference is
   global or per-workspace.
5. **Tiled metadata (P1-5):** scope — class/type only, or full custom properties
   (+ later animation/collision)?
