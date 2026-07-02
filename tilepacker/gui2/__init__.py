"""Minimal (gui2) tilepacker desktop app (PySide6).

A deliberately small alternative to :mod:`tilepacker.gui_app`, with only the
core workflow: import source images, overlay an isometric split grid, drag to
select a diamond-shaped area of cells, Copy them to the clipboard, Paste them
into an isometric tileset preview, and Export the result as a PNG + ``.tsx``.

``import tilepacker.gui2`` does not import PySide6; the Qt-dependent entry point
is imported lazily inside :func:`launch`.
"""

from __future__ import annotations

__all__ = ["launch"]


def launch(argv=None) -> int:
    """Launch the minimal GUI (imports PySide6 lazily)."""
    try:
        from tilepacker.gui2.app import launch as _launch
    except ImportError as exc:  # PySide6 missing or app module unavailable.
        print(
            "Error: the GUI requires PySide6. Install it with:\n"
            "    pip install PySide6\n"
            f"(import failed: {exc})"
        )
        return 1
    return _launch(argv)
