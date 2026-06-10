#!/usr/bin/env bash
# =============================================================================
# tilepacker demo script
#
# This demo must use the Python from the project's virtual environment.
#   <project-root>/.venv/bin/python   (interpreter with Pillow / numpy installed)
# Using the system Python may fail because Pillow and others are missing.
#
# Run:
#   bash examples/demo.sh
# Or after granting execute permission:
#   chmod +x examples/demo.sh && ./examples/demo.sh
# =============================================================================

set -euo pipefail

# --- Path setup -------------------------------------------------------------
# Compute the directory this script lives in (examples/) and the project root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Virtual environment Python. Fall back to the system python3 with a warning if missing.
VENV_PY="${PROJECT_ROOT}/.venv/bin/python"
if [[ -x "${VENV_PY}" ]]; then
    PY="${VENV_PY}"
else
    echo "warning: ${VENV_PY} not found; proceeding with the system python3." >&2
    PY="python3"
fi

# Add the project root to PYTHONPATH so the tilepacker package can be imported.
export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# Directories to collect the work output.
SAMPLE_DIR="${SCRIPT_DIR}/sample_tiles"     # individual sample tiles
OUT_DIR="${SCRIPT_DIR}/out"                 # demo output
mkdir -p "${OUT_DIR}"

echo "== tilepacker demo =="
echo "Python:       ${PY}"
echo "Project root: ${PROJECT_ROOT}"
echo

# --- 0) Generate sample tiles -----------------------------------------------
# Create twelve 32x32 tiles with patterns over a solid background (#ff00ff).
echo "[0] Generate sample tiles"
"${PY}" "${SCRIPT_DIR}/generate_sample_tiles.py" \
    --count 12 --size 32 --out "${SAMPLE_DIR}"
echo

# --- 1) pack: individual tiles -> uniform-grid tileset (PNG + .tsx) ----------
# The most basic usage. A .tsx definition file is generated alongside so you can open it directly in Tiled.
echo "[1] pack: generate tileset PNG + .tsx"
"${PY}" -m tilepacker pack "${SAMPLE_DIR}"/*.png \
    -o "${OUT_DIR}/tileset.png" \
    -tw 32 -th 32 \
    --columns 4 \
    --name demo_tileset
echo

# --- 1b) pack + background removal (rmbg) + dedup/drop-empty + extrude -------
# --remove-bg auto-samples the background color from each tile's four corners and makes it transparent.
# --extrude 2 is padding that prevents tile edges from bleeding (tearing) when scaling.
echo "[1b] pack: remove background + dedup + extrude"
"${PY}" -m tilepacker pack "${SAMPLE_DIR}"/*.png \
    -o "${OUT_DIR}/tileset_clean.png" \
    -tw 32 -th 32 \
    --remove-bg --bg-tolerance 16 \
    --extrude 2 \
    --dedup --drop-empty \
    --name demo_clean \
    --tsj
echo

# --- 2) slice: cut the tileset sheet made above back into individual tiles ---
# Decompose a spritesheet (uniform grid) into individual PNGs. Saved to --output-dir.
echo "[2] slice: split the tileset sheet into individual tiles"
"${PY}" -m tilepacker slice "${OUT_DIR}/tileset.png" \
    -o "${OUT_DIR}/sliced" \
    -tw 32 -th 32
echo

# --- 3) resize: resize individual tiles to 16x16 ----------------------------
# Pixel art uses the nearest filter to avoid interpolation loss.
echo "[3] resize: 32x32 -> 16x16"
"${PY}" -m tilepacker resize "${SAMPLE_DIR}"/*.png \
    -o "${OUT_DIR}/resized16" \
    -tw 16 -th 16 \
    --resize-mode fit --resample nearest
echo

# --- 4) rmbg: make the background color transparent and save separately -----
# Remove the sample tiles' background (#ff00ff) via corner auto-sampling.
echo "[4] rmbg: remove background (#ff00ff)"
"${PY}" -m tilepacker rmbg "${SAMPLE_DIR}"/*.png \
    -o "${OUT_DIR}/nobg" \
    --bg-color "#ff00ff" --bg-tolerance 16
echo

# --- 5) info: check the output's size and inferred grid ---------------------
echo "[5] info: check tileset info"
"${PY}" -m tilepacker info "${OUT_DIR}/tileset.png"
echo

echo "== Demo complete. Output: ${OUT_DIR} =="
