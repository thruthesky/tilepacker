"""Tests for tilepacker.core.config."""

from __future__ import annotations

import pytest

from tilepacker.core.config import (
    PackConfig,
    RESAMPLE_FILTERS,
    RESIZE_MODES,
    SORT_MODES,
    parse_color,
)


# --- parse_color -----------------------------------------------------------
def test_parse_color_none_variants():
    assert parse_color(None) is None
    assert parse_color("") is None
    assert parse_color("none") is None
    assert parse_color("transparent") is None
    assert parse_color("NONE") is None  # case-insensitive


def test_parse_color_hex_short():
    # #rgb -> each digit doubled.
    assert parse_color("#f00") == (255, 0, 0, 255)
    assert parse_color("#0f0") == (0, 255, 0, 255)


def test_parse_color_hex_long_and_alpha():
    assert parse_color("#112233") == (0x11, 0x22, 0x33, 255)
    assert parse_color("#11223344") == (0x11, 0x22, 0x33, 0x44)


def test_parse_color_comma():
    assert parse_color("10,20,30") == (10, 20, 30, 255)
    assert parse_color("10,20,30,40") == (10, 20, 30, 40)


def test_parse_color_sequence():
    assert parse_color([1, 2, 3]) == (1, 2, 3, 255)
    assert parse_color((1, 2, 3, 4)) == (1, 2, 3, 4)


def test_parse_color_invalid_raises():
    with pytest.raises(ValueError):
        parse_color("#12")  # invalid hex length
    with pytest.raises(ValueError):
        parse_color("not-a-color")
    with pytest.raises(ValueError):
        parse_color([1, 2])  # too few components
    with pytest.raises(ValueError):
        parse_color([1, 2, 3, 4, 5])  # too many components
    with pytest.raises(ValueError):
        parse_color([300, 0, 0])  # out of range


# --- validate --------------------------------------------------------------
def test_validate_ok_default():
    PackConfig().validate()  # defaults must be valid.


def test_validate_bad_tile_size():
    with pytest.raises(ValueError):
        PackConfig(tile_width=0).validate()
    with pytest.raises(ValueError):
        PackConfig(tile_height=-1).validate()


def test_validate_negative_fields():
    for field in ("columns", "margin", "spacing", "extrude", "bg_tolerance"):
        with pytest.raises(ValueError):
            PackConfig(**{field: -1}).validate()


def test_validate_bad_enums():
    with pytest.raises(ValueError):
        PackConfig(resize_mode="bogus").validate()
    with pytest.raises(ValueError):
        PackConfig(resample="bogus").validate()
    with pytest.raises(ValueError):
        PackConfig(sort="bogus").validate()


def test_validate_bg_tolerance_upper_bound():
    PackConfig(bg_tolerance=441).validate()  # boundary value allowed.
    with pytest.raises(ValueError):
        PackConfig(bg_tolerance=442).validate()


def test_enum_sets_contain_expected():
    assert "fit" in RESIZE_MODES and "stretch" in RESIZE_MODES
    assert "nearest" in RESAMPLE_FILTERS and "lanczos" in RESAMPLE_FILTERS
    assert "natural" in SORT_MODES and "none" in SORT_MODES


# --- to_dict / from_dict round-trip ----------------------------------------
def test_to_dict_serializes_colors_as_lists():
    cfg = PackConfig(pad_color=(1, 2, 3, 4), background=(5, 6, 7, 8))
    d = cfg.to_dict()
    assert d["pad_color"] == [1, 2, 3, 4]
    assert d["background"] == [5, 6, 7, 8]
    assert d["bg_color"] is None


def test_roundtrip_from_dict():
    cfg = PackConfig(
        tile_width=16,
        tile_height=24,
        columns=4,
        margin=2,
        spacing=1,
        extrude=1,
        resize_mode="stretch",
        resample="lanczos",
        pad_color=(10, 20, 30, 40),
        background=(1, 2, 3, 4),
        bg_remove=True,
        bg_color=(9, 9, 9, 255),
        bg_tolerance=30,
        sort="natural",
        deduplicate=True,
        drop_empty=True,
        name="myset",
    )
    restored = PackConfig.from_dict(cfg.to_dict())
    assert restored == cfg


def test_from_dict_ignores_unknown_keys():
    cfg = PackConfig.from_dict({"tile_width": 48, "bogus_key": 123})
    assert cfg.tile_width == 48


def test_from_dict_parses_color_strings():
    cfg = PackConfig.from_dict({"pad_color": "#ff0000", "bg_color": "1,2,3"})
    assert cfg.pad_color == (255, 0, 0, 255)
    assert cfg.bg_color == (1, 2, 3, 255)


def test_copy_overrides():
    cfg = PackConfig(tile_width=32, name="a")
    other = cfg.copy(tile_width=64, name="b")
    assert other.tile_width == 64 and other.name == "b"
    # the original is left unchanged.
    assert cfg.tile_width == 32 and cfg.name == "a"
