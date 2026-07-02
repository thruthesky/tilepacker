#!/usr/bin/env bash
# Launch the minimal (isometric-only) tilepacker GUI using the project's virtualenv.
# Usage: ./gui2.sh
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/tilepacker gui2 "$@"
