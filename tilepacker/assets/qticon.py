"""Qt-side application icon wiring shared by both GUI launchers.

Kept separate from the package ``__init__`` so importing
:mod:`tilepacker.assets` never pulls in PySide6.
"""

from __future__ import annotations

from tilepacker.assets import app_icon_path

__all__ = ["apply_app_icon"]


def apply_app_icon(app) -> bool:
    """Set the bundled icon on ``app`` (a ``QApplication``); best-effort.

    On macOS this also replaces the Dock icon of the running process (the
    generic Python rocket for an unbundled interpreter); elsewhere top-level
    windows inherit it for the taskbar. Returns ``True`` when the icon was
    applied, ``False`` when the asset is missing or unreadable — the app must
    still launch normally in that case.
    """
    path = app_icon_path()
    if path is None:
        return False
    from PySide6 import QtGui

    icon = QtGui.QIcon(str(path))
    if icon.isNull():
        return False
    app.setWindowIcon(icon)
    return True
