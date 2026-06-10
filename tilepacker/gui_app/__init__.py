"""tilepacker desktop GUI application (PySide6).

The GUI lets you import images, edit each tile (crop, rotate, remove background,
hue/brightness/etc.), arrange them on an isometric or orthogonal grid, and
export a uniform-grid tileset (PNG + .tsx/.tsj) for the Tiled map editor.

``import tilepacker.gui_app`` does not import PySide6; the Qt-dependent entry
point is imported lazily inside :func:`launch`.
"""

from __future__ import annotations

__all__ = ["launch"]


def launch(argv=None) -> int:
    """Launch the GUI application.

    PySide6 and the window classes are imported lazily here so that importing
    this package (e.g. for the pure model/edit code) never requires Qt.

    Args:
        argv: Optional argument list forwarded to the Qt application.

    Returns:
        The process exit code (0 on a clean quit, 1 if Qt is unavailable).
    """
    try:
        from tilepacker.gui_app.app import launch as _launch
    except ImportError as exc:  # PySide6 missing or app module unavailable.
        print(
            "Error: the GUI requires PySide6. Install it with:\n"
            "    pip install PySide6\n"
            f"(import failed: {exc})"
        )
        return 1
    return _launch(argv)
