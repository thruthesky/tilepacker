"""Bundled image assets shared by both tilepacker GUIs.

This package is Qt-free so it stays importable headless; the Qt-side icon
wiring lives in :mod:`tilepacker.assets.qticon`. Paths are resolved relative
to this file, never the CWD, because the entry points run from anywhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

__all__ = ["app_icon_path"]

_ICON_FILENAME = "icon.png"


def app_icon_path() -> Optional[Path]:
    """Return the bundled application icon path, or ``None`` when absent.

    The icon is optional: callers must treat ``None`` as "launch without a
    custom icon", never as an error.
    """
    path = Path(__file__).resolve().parent / _ICON_FILENAME
    return path if path.is_file() else None
