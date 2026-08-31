"""Tests for the shared application icon asset and its loaders.

Covers the Qt-free path helper (``tilepacker.assets``), the committed PNG
asset itself, and the Qt-side ``apply_app_icon`` used by both GUI launchers.
Runs under the offscreen Qt platform plugin; the Qt half is skipped entirely
when PySide6 is absent.
"""

from __future__ import annotations

import os

# Must be set before any QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PIL import Image

from tilepacker.assets import app_icon_path


# -- Qt-free path helper -------------------------------------------------

def test_app_icon_path_returns_existing_png():
    path = app_icon_path()
    assert path is not None
    assert path.is_file()
    assert path.suffix == ".png"


def test_app_icon_path_missing_returns_none(monkeypatch):
    import tilepacker.assets as assets

    monkeypatch.setattr(assets, "_ICON_FILENAME", "no-such-icon.png")
    assert app_icon_path() is None


# -- the committed asset -------------------------------------------------

def test_icon_asset_is_square_rgba():
    path = app_icon_path()
    with Image.open(path) as im:
        assert im.width == im.height
        assert im.width in (512, 1024)
        assert im.mode == "RGBA"


# -- Qt-side wiring helper -----------------------------------------------

pytest.importorskip("PySide6")

from PySide6 import QtGui, QtWidgets  # noqa: E402

from tilepacker.assets.qticon import apply_app_icon  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_apply_app_icon_sets_application_icon(qapp):
    qapp.setWindowIcon(QtGui.QIcon())
    assert apply_app_icon(qapp) is True
    assert not qapp.windowIcon().isNull()


def test_apply_app_icon_missing_asset_is_noop(qapp, monkeypatch):
    import tilepacker.assets as assets

    monkeypatch.setattr(assets, "_ICON_FILENAME", "no-such-icon.png")
    qapp.setWindowIcon(QtGui.QIcon())
    assert apply_app_icon(qapp) is False
    assert qapp.windowIcon().isNull()
