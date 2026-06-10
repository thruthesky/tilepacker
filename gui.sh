#!/usr/bin/env bash
# Launch the tilepacker desktop GUI (PySide6) using the project's virtualenv.
# Usage: ./gui.sh
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/tilepacker gui "$@"
