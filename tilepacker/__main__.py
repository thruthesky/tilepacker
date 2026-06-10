"""``python -m tilepacker`` entry point — runs the CLI ``main()``."""

from __future__ import annotations

import sys

from tilepacker.cli import main

if __name__ == "__main__":
    sys.exit(main())
