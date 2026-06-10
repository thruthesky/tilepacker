"""Conversion helpers between Pillow images and Qt (PySide6) image types.

Only this module imports PySide6 among the non-widget helpers, so the rest of
the model/edit code stays Qt-free and unit-testable. Conversions always go
through RGBA for predictable channel order.
"""

from __future__ import annotations

from PIL import Image
from PySide6 import QtGui

from tilepacker.core import imageops

__all__ = ["pil_to_qimage", "pil_to_qpixmap", "qimage_to_pil"]


def pil_to_qimage(img: Image.Image) -> QtGui.QImage:
    """Convert a Pillow image to a standalone ``QImage`` (RGBA8888).

    The returned QImage owns its pixel buffer (``.copy()``), so it stays valid
    after the source bytes are garbage-collected.

    Args:
        img: Input image (any mode).

    Returns:
        A ``QImage`` in ``Format_RGBA8888``.
    """
    rgba = imageops.ensure_rgba(img)
    data = rgba.tobytes("raw", "RGBA")
    qimg = QtGui.QImage(
        data, rgba.width, rgba.height, QtGui.QImage.Format.Format_RGBA8888
    )
    return qimg.copy()


def pil_to_qpixmap(img: Image.Image) -> QtGui.QPixmap:
    """Convert a Pillow image to a ``QPixmap`` for display in widgets.

    Args:
        img: Input image (any mode).

    Returns:
        A ``QPixmap`` built from the image.
    """
    return QtGui.QPixmap.fromImage(pil_to_qimage(img))


def qimage_to_pil(qimg: QtGui.QImage) -> Image.Image:
    """Convert a ``QImage`` to a Pillow RGBA image.

    Args:
        qimg: The source ``QImage`` (any format).

    Returns:
        A Pillow image in ``RGBA`` mode.
    """
    converted = qimg.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    width = converted.width()
    height = converted.height()
    ptr = converted.constBits()
    buf = bytes(ptr[: width * height * 4])
    return Image.frombytes("RGBA", (width, height), buf)
