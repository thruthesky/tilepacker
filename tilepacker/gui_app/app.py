"""Application entry point for the tilepacker GUI.

Provides :func:`launch`, which reuses an existing ``QApplication`` when one is
already running (so it can be embedded), creates and shows the
:class:`MainWindow`, and runs the Qt event loop. The module is runnable
directly (``python -m tilepacker.gui_app.app``).
"""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from PySide6 import QtWidgets

from tilepacker.assets.qticon import apply_app_icon
from tilepacker.gui_app.main_window import MainWindow

__all__ = ["launch"]


def launch(argv: Optional[Sequence[str]] = None) -> int:
    """Create (or reuse) the QApplication, show the main window, and run.

    Args:
        argv: Command-line arguments. When ``None``, ``sys.argv`` is used.

    Returns:
        The Qt application's exit code.
    """
    if argv is None:
        argv = sys.argv

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(list(argv))

    apply_app_icon(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(launch())
