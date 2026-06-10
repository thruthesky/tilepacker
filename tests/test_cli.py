"""Tests for tilepacker.cli."""

from __future__ import annotations

import json
import os

from PIL import Image

from tilepacker import cli

from .conftest import make_tile


def _save_tiles(dir_path, n=4):
    """Save n solid-color tiles into dir_path and return the list of paths."""
    paths = []
    palette = [
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
        (255, 255, 0, 255),
    ]
    for i in range(n):
        p = os.path.join(dir_path, f"t{i}.png")
        make_tile(palette[i % len(palette)], (16, 16)).save(p, "PNG")
        paths.append(p)
    return paths


# --- expand_inputs ---------------------------------------------------------
def test_expand_inputs_glob(tmp_path):
    _save_tiles(str(tmp_path), 3)
    pattern = os.path.join(str(tmp_path), "*.png")
    expanded = cli.expand_inputs([pattern])
    assert len(expanded) == 3
    assert all(p.endswith(".png") for p in expanded)


def test_expand_inputs_keeps_missing_literal():
    expanded = cli.expand_inputs(["/does/not/exist_xyz.png"])
    assert expanded == ["/does/not/exist_xyz.png"]


# --- build_parser ----------------------------------------------------------
def test_build_parser_returns_parser():
    parser = cli.build_parser()
    args = parser.parse_args(["pack", "a.png", "-o", "out.png"])
    assert args.command == "pack"
    assert args.output == "out.png"


# --- main: pack ------------------------------------------------------------
def test_main_pack_returns_zero_and_creates_output(tmp_path):
    paths = _save_tiles(str(tmp_path), 4)
    out_png = tmp_path / "tileset.png"
    rc = cli.main(
        [
            "pack",
            *paths,
            "-o",
            str(out_png),
            "-tw",
            "16",
            "-th",
            "16",
            "-c",
            "2",
            "--tsj",
        ]
    )
    assert rc == 0
    assert out_png.exists()
    assert (tmp_path / "tileset.tsx").exists()
    assert (tmp_path / "tileset.tsj").exists()
    with Image.open(out_png) as im:
        assert im.size == (32, 32)


def test_main_pack_no_tsx(tmp_path):
    paths = _save_tiles(str(tmp_path), 2)
    out_png = tmp_path / "out.png"
    rc = cli.main(["pack", *paths, "-o", str(out_png), "-tw", "16", "-th", "16", "--no-tsx"])
    assert rc == 0
    assert out_png.exists()
    assert not (tmp_path / "out.tsx").exists()


def test_main_pack_invalid_config_returns_one(tmp_path):
    paths = _save_tiles(str(tmp_path), 1)
    out_png = tmp_path / "out.png"
    rc = cli.main(["pack", *paths, "-o", str(out_png), "-tw", "0"])
    assert rc == 1


# --- main: slice (basic slice + repack) -----------------------------------
def _make_sheet(path, cols=4, tile=16):
    sheet = Image.new("RGBA", (cols * tile, tile), (0, 0, 0, 0))
    px = sheet.load()
    for c in range(cols):
        for y in range(tile):
            for x in range(tile):
                px[c * tile + x, y] = (10 + c * 40, 0, 0, 255)
    sheet.save(path, "PNG")


def test_main_slice_default(tmp_path):
    sheet_path = tmp_path / "sheet.png"
    _make_sheet(str(sheet_path), cols=4, tile=16)
    out_dir = tmp_path / "out"
    rc = cli.main(
        ["slice", str(sheet_path), "-o", str(out_dir), "-tw", "16", "-th", "16"]
    )
    assert rc == 0
    saved = sorted(os.listdir(str(out_dir)))
    assert len(saved) == 4


def test_main_slice_repack(tmp_path):
    sheet_path = tmp_path / "sheet.png"
    _make_sheet(str(sheet_path), cols=4, tile=16)
    out_png = tmp_path / "repacked.png"
    rc = cli.main(
        [
            "slice",
            str(sheet_path),
            "--repack",
            "--output",
            str(out_png),
            "-tw",
            "16",
            "-th",
            "16",
            "-c",
            "2",
        ]
    )
    assert rc == 0
    assert out_png.exists()
    assert (tmp_path / "repacked.tsx").exists()


# --- main: resize ----------------------------------------------------------
def test_main_resize(tmp_path):
    paths = _save_tiles(str(tmp_path), 3)
    out_dir = tmp_path / "resized"
    rc = cli.main(
        ["resize", *paths, "-o", str(out_dir), "-tw", "32", "-th", "32"]
    )
    assert rc == 0
    outs = sorted(os.listdir(str(out_dir)))
    assert len(outs) == 3
    with Image.open(out_dir / outs[0]) as im:
        assert im.size == (32, 32)


# --- main: rmbg ------------------------------------------------------------
def test_main_rmbg(tmp_path):
    p = tmp_path / "red.png"
    make_tile((255, 0, 0, 255), (16, 16)).save(p, "PNG")
    out_dir = tmp_path / "clean"
    rc = cli.main(
        ["rmbg", str(p), "-o", str(out_dir), "--bg-color", "255,0,0,255"]
    )
    assert rc == 0
    out_file = out_dir / "red.png"
    assert out_file.exists()
    with Image.open(out_file) as im:
        assert im.convert("RGBA").getpixel((0, 0))[3] == 0


# --- main: info ------------------------------------------------------------
def test_main_info(tmp_path, capsys):
    p = tmp_path / "img.png"
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(p, "PNG")
    rc = cli.main(["info", str(p)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "64x64" in out


# --- main: no subcommand ---------------------------------------------------
def test_main_no_command_launches_gui(monkeypatch):
    # With no subcommand, the CLI launches the desktop GUI (tilepacker is
    # primarily a GUI app). Stub the launcher so no window opens during the
    # test, and verify it is invoked and its return code is propagated.
    import tilepacker.gui_app as gui_app

    calls = []
    monkeypatch.setattr(gui_app, "launch", lambda argv=None: (calls.append(argv), 0)[1])
    assert cli.main([]) == 0
    assert calls == [None]
