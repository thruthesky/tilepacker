"""Pillow <-> Qt conversion helpers for the minimal (gui2) app.

Kept tiny and self-contained so gui2 does not depend on the legacy gui_app.
Conversions always go through RGBA for a predictable channel order.
"""

from __future__ import annotations

from PIL import Image
from PySide6 import QtGui

__all__ = ["pil_to_qimage", "pil_to_qpixmap"]


def pil_to_qimage(img: Image.Image) -> QtGui.QImage:
    """Convert a Pillow image to a standalone ``QImage`` (RGBA8888).

    The returned QImage owns its pixel buffer (``.copy()``), so it stays valid
    after the source bytes are garbage-collected.
    """
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QtGui.QImage(data, rgba.width, rgba.height, QtGui.QImage.Format.Format_RGBA8888)
    return qimg.copy()


def pil_to_qpixmap(img: Image.Image) -> QtGui.QPixmap:
    """Convert a Pillow image to a ``QPixmap`` for display in widgets."""
    return QtGui.QPixmap.fromImage(pil_to_qimage(img))
