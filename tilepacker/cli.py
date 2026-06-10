"""tilepacker command-line interface (CLI).

Provides an argparse-based subcommand entry point. The entry point is :func:`main`,
which takes ``argv`` and returns an integer exit code (0 on success, 1 on failure).

Subcommands:
  * ``pack``   - Pack individual tile images into a uniform-grid tileset (PNG + .tsx/.tsj).
  * ``slice``  - Slice a spritesheet into a grid and save individual tiles (default),
                 or recombine into a tileset with ``--repack``.
  * ``resize`` - Resize multiple images to a given cell size and save them.
  * ``rmbg``   - Remove the background from multiple images and save them.
  * ``info``   - Print the size and estimated grid info of images/tilesets.
  * ``gui``    - Launch the graphical user interface (:mod:`tilepacker.gui`).

Design policy:
  * All images are handled in Pillow RGBA mode (via the ``imageops`` submodule).
  * Color options are normalized with :func:`tilepacker.core.config.parse_color`.
  * Input paths are expanded once more with ``glob.glob`` (in case the shell did not
    expand the glob). If there are no matches, the input string is used as-is.

Dependencies: standard library + core submodules (via Pillow).
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from typing import List, Optional, Sequence, Tuple

from PIL import Image

from tilepacker.core.config import (
    PackConfig,
    RESAMPLE_FILTERS,
    RESIZE_MODES,
    SORT_MODES,
    parse_color,
)
from tilepacker.core import export, imageops, slicer

__all__ = [
    "build_parser",
    "expand_inputs",
    "main",
]

#: Common tile sizes (px) to try as estimated grid candidates in the info subcommand.
_COMMON_TILE_SIZES: Tuple[int, ...] = (8, 16, 24, 32, 48, 64, 96, 128)


def expand_inputs(patterns: Sequence[str]) -> List[str]:
    """Expand a list of input paths/glob patterns into a list of actual file paths.

    Each pattern is expanded with ``glob.glob``. If the shell already expanded the
    glob, the pattern is a single existing path and remains as one item. When there
    are multiple matches, they are sorted lexicographically for a deterministic order.
    If there are no matches at all (a nonexistent path or an empty glob), the original
    string is left as-is (so a clear error surfaces later during loading). Duplicate
    paths are kept only once, preserving order.

    Args:
        patterns: Sequence of file path or glob pattern strings.

    Returns:
        A list of path strings that have been expanded, sorted, and deduplicated.
    """
    result: List[str] = []
    seen = set()
    for pattern in patterns:
        matches = sorted(glob.glob(str(pattern)))
        candidates = matches if matches else [str(pattern)]
        for path in candidates:
            if path not in seen:
                seen.add(path)
                result.append(path)
    return result


def _add_color_argument(parser: argparse.ArgumentParser, *names, help: str) -> None:
    """Helper that registers a color option using ``parse_color`` as its type."""
    parser.add_argument(*names, type=parse_color, default=None, metavar="COLOR", help=help)


def build_parser() -> argparse.ArgumentParser:
    """Build and return tilepacker's full argparse parser (including subparsers).

    Returns:
        The configured top-level :class:`argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        prog="tilepacker",
        description="Pack individual tile images into a uniform-grid tileset for Tiled.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    resize_modes = sorted(RESIZE_MODES)
    resample_filters = sorted(RESAMPLE_FILTERS)
    sort_modes = sorted(SORT_MODES)

    # ------------------------------------------------------------------ pack
    p_pack = subparsers.add_parser(
        "pack",
        help="Pack individual tiles into a uniform-grid tileset.",
        description="Pack individual tile images into a PNG tileset and .tsx/.tsj definition files.",
    )
    p_pack.add_argument("inputs", nargs="+", help="Tile image files or glob patterns (one or more).")
    p_pack.add_argument("-o", "--output", required=True, help="Output tileset PNG path (required).")
    p_pack.add_argument("-tw", "--tile-width", type=int, default=32, help="Tile cell width (px). Default 32.")
    p_pack.add_argument("-th", "--tile-height", type=int, default=32, help="Tile cell height (px). Default 32.")
    p_pack.add_argument("-c", "--columns", type=int, default=0, help="Number of tileset columns. 0 means auto. Default 0.")
    p_pack.add_argument("--margin", type=int, default=0, help="Outer border margin of the tileset (px). Default 0.")
    p_pack.add_argument("--spacing", type=int, default=0, help="Spacing between tiles (px). Default 0.")
    p_pack.add_argument("--extrude", type=int, default=0, help="Extrude each tile's edges outward (px). Default 0.")
    p_pack.add_argument("--resize-mode", choices=resize_modes, default="fit", help="Resize mode. Default fit.")
    p_pack.add_argument("--resample", choices=resample_filters, default="nearest", help="Resampling filter. Default nearest.")
    _add_color_argument(p_pack, "--pad-color", help="Padding fill color for fit mode (e.g. '#rrggbb', 'r,g,b,a', none).")
    _add_color_argument(p_pack, "--background", help="Background color filling the bottom of each cell.")
    p_pack.add_argument("--remove-bg", dest="bg_remove", action="store_true", help="Enable background removal.")
    _add_color_argument(p_pack, "--bg-color", help="Background color to remove. If unset, auto-sampled from the four corners.")
    p_pack.add_argument("--bg-tolerance", type=int, default=0, help="Background color distance tolerance (0..441). Default 0.")
    p_pack.add_argument("--bg-flood", action="store_true", help="Remove the background via corner flood fill.")
    p_pack.add_argument("--trim", action="store_true", help="Automatically trim each tile's transparent border.")
    p_pack.add_argument("--sort", choices=sort_modes, default="none", help="Input sort mode. Default none.")
    p_pack.add_argument("--dedup", dest="deduplicate", action="store_true", help="Remove duplicate tiles with identical pixels.")
    p_pack.add_argument("--drop-empty", action="store_true", help="Remove fully transparent tiles.")
    p_pack.add_argument("--name", default="tileset", help="Tileset name (.tsx name attribute). Default tileset.")
    p_pack.add_argument(
        "--tsx",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="(Whether to generate the .tsx definition file. Generated by default; disable with --no-tsx.)",
    )
    p_pack.add_argument("--tsj", action="store_true", help="Also generate a .tsj (JSON) definition file.")
    p_pack.set_defaults(func=_cmd_pack)

    # ----------------------------------------------------------------- slice
    p_slice = subparsers.add_parser(
        "slice",
        help="Slice a spritesheet into a grid or repack it.",
        description="Slice a spritesheet into a uniform grid and save individual tiles (or repack with --repack).",
    )
    p_slice.add_argument("sheet", help="Path to the input spritesheet image.")
    p_slice.add_argument("-o", "--output-dir", help="Directory to save the sliced tiles (default mode).")
    p_slice.add_argument("--output", help="Output tileset PNG path when repacking (--repack).")
    p_slice.add_argument("-tw", "--tile-width", type=int, default=32, help="Cell width (px). Default 32.")
    p_slice.add_argument("-th", "--tile-height", type=int, default=32, help="Cell height (px). Default 32.")
    p_slice.add_argument("--margin", type=int, default=0, help="Outer border margin of the input sheet (px). Default 0.")
    p_slice.add_argument("--spacing", type=int, default=0, help="Spacing between cells in the input sheet (px). Default 0.")
    p_slice.add_argument("--sheet-offset", default="0,0", help="Input sheet start offset 'x,y'. Default 0,0.")
    p_slice.add_argument("-c", "--columns", type=int, default=0, help="Number of tileset columns when repacking. 0 means auto.")
    p_slice.add_argument("--extrude", type=int, default=0, help="Extrude each tile's edges when repacking (px).")
    p_slice.add_argument("--name", default="tileset", help="Tileset name when repacking. Default tileset.")
    p_slice.add_argument("--drop-empty", action="store_true", help="Exclude fully transparent tiles.")
    p_slice.add_argument("--dedup", dest="deduplicate", action="store_true", help="Remove duplicate tiles with identical pixels when repacking.")
    p_slice.add_argument("--repack", action="store_true", help="Recombine the sliced tiles back into a tileset.")
    p_slice.add_argument(
        "--tsx",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="(Whether to generate the .tsx when repacking. Generated by default.)",
    )
    p_slice.add_argument("--tsj", action="store_true", help="Also generate a .tsj when repacking.")
    p_slice.set_defaults(func=_cmd_slice)

    # ---------------------------------------------------------------- resize
    p_resize = subparsers.add_parser(
        "resize",
        help="Resize multiple images to a given cell size.",
        description="Convert input images to the given cell size and save them to the output directory.",
    )
    p_resize.add_argument("inputs", nargs="+", help="Input image files or glob patterns (one or more).")
    p_resize.add_argument("-o", "--output-dir", required=True, help="Directory to save the results (required).")
    p_resize.add_argument("-tw", "--tile-width", type=int, default=32, help="Target width (px). Default 32.")
    p_resize.add_argument("-th", "--tile-height", type=int, default=32, help="Target height (px). Default 32.")
    p_resize.add_argument("--resize-mode", choices=resize_modes, default="fit", help="Resize mode. Default fit.")
    p_resize.add_argument("--resample", choices=resample_filters, default="nearest", help="Resampling filter. Default nearest.")
    _add_color_argument(p_resize, "--pad-color", help="Padding fill color for fit mode.")
    p_resize.set_defaults(func=_cmd_resize)

    # ------------------------------------------------------------------ rmbg
    p_rmbg = subparsers.add_parser(
        "rmbg",
        help="Remove the background from multiple images.",
        description="Make the background color of input images transparent and save them to the output directory.",
    )
    p_rmbg.add_argument("inputs", nargs="+", help="Input image files or glob patterns (one or more).")
    p_rmbg.add_argument("-o", "--output-dir", required=True, help="Directory to save the results (required).")
    _add_color_argument(p_rmbg, "--bg-color", help="Background color to remove. If unset, auto-sampled from the four corners.")
    p_rmbg.add_argument("--bg-tolerance", type=int, default=0, help="Background color distance tolerance (0..441). Default 0.")
    p_rmbg.add_argument("--bg-flood", action="store_true", help="Remove the background via corner flood fill.")
    p_rmbg.set_defaults(func=_cmd_rmbg)

    # ------------------------------------------------------------------ info
    p_info = subparsers.add_parser(
        "info",
        help="Print the size and estimated grid of images/tilesets.",
        description="Print each image's size, mode, and the inferable uniform-grid candidates.",
    )
    p_info.add_argument("paths", nargs="+", help="Image files or glob patterns to inspect (one or more).")
    p_info.set_defaults(func=_cmd_info)

    # ------------------------------------------------------------------- gui
    p_gui = subparsers.add_parser(
        "gui",
        help="Launch the graphical user interface.",
        description="Run the tilepacker GUI.",
    )
    p_gui.set_defaults(func=_cmd_gui)

    return parser


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------
def _parse_xy(text: str) -> Tuple[int, int]:
    """Convert an 'x,y' formatted string into an ``(int, int)`` tuple.

    Args:
        text: A string of two comma-separated integers, like ``"0,0"``.

    Returns:
        An ``(x, y)`` integer tuple.

    Raises:
        ValueError: When it cannot be parsed as two integers.
    """
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 2:
        raise ValueError(f"Offset must be in 'x,y' format: {text!r}")
    return (int(parts[0]), int(parts[1]))


def _resolve_output_path(out_dir: str, src_path: str, used: set) -> Tuple[str, bool]:
    """Build an output path, appending a suffix to guarantee uniqueness on basename collision.

    Prevents the silent data loss where a later file overwrites an earlier one when
    same-named inputs from different directories (e.g. a/tile.png, b/tile.png) are
    written into a single output directory.

    Args:
        out_dir: The output directory.
        src_path: The input file path (the output name is built from its basename).
        used: Set of already-used output filenames (maintained by the caller). This
            function updates it.

    Returns:
        ``(out_path, collided)``. When ``collided`` is True, a suffix was appended to
        avoid a collision.
    """
    base = os.path.splitext(os.path.basename(src_path))[0]
    name = base + ".png"
    collided = False
    n = 1
    while name in used:
        collided = True
        name = f"{base}_{n}.png"
        n += 1
    used.add(name)
    return os.path.join(out_dir, name), collided


def _cmd_pack(args: argparse.Namespace) -> int:
    """``pack`` subcommand: pack individual tiles into a tileset."""
    inputs = expand_inputs(args.inputs)
    if not inputs:
        print("Error: no input tiles.", file=sys.stderr)
        return 1

    config = PackConfig(
        tile_width=args.tile_width,
        tile_height=args.tile_height,
        columns=args.columns,
        margin=args.margin,
        spacing=args.spacing,
        extrude=args.extrude,
        resize_mode=args.resize_mode,
        resample=args.resample,
        pad_color=args.pad_color,
        background=args.background,
        bg_remove=args.bg_remove,
        bg_color=args.bg_color,
        bg_tolerance=args.bg_tolerance,
        bg_flood=args.bg_flood,
        trim=args.trim,
        sort=args.sort,
        deduplicate=args.deduplicate,
        drop_empty=args.drop_empty,
        name=args.name,
    )
    try:
        config.validate()
    except ValueError as exc:
        print(f"Error: invalid configuration: {exc}", file=sys.stderr)
        return 1

    try:
        result = export.pack_from_files(
            inputs,
            config,
            args.output,
            write_tsx=args.tsx,
            write_tsj=args.tsj,
        )
    except (OSError, ValueError) as exc:
        print(f"Error: packing failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Packing complete: {result.image_path} "
        f"({result.width}x{result.height}px, "
        f"{result.tile_count} tiles, {result.columns} cols x {result.rows} rows)"
    )
    if result.tsx_path:
        print(f"  .tsx written: {result.tsx_path}")
    if result.tsj_path:
        print(f"  .tsj written: {result.tsj_path}")
    return 0


def _cmd_slice(args: argparse.Namespace) -> int:
    """``slice`` subcommand: slice a spritesheet, or repack it (when --repack)."""
    try:
        offset = _parse_xy(args.sheet_offset)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not os.path.exists(args.sheet):
        print(f"Error: input sheet not found: {args.sheet}", file=sys.stderr)
        return 1

    # --- (a) Repack mode -------------------------------------------------
    if args.repack:
        out_path = args.output or args.output_dir
        if not out_path:
            print("Error: --repack mode requires --output (tileset PNG path).", file=sys.stderr)
            return 1
        # If -o received an (existing) directory, save '{name}.png' inside it.
        if os.path.isdir(out_path) or str(out_path).endswith(os.sep):
            out_path = os.path.join(out_path, f"{args.name}.png")
        config = PackConfig(
            tile_width=args.tile_width,
            tile_height=args.tile_height,
            columns=args.columns,
            extrude=args.extrude,
            drop_empty=args.drop_empty,
            deduplicate=args.deduplicate,
            name=args.name,
        )
        try:
            config.validate()
        except ValueError as exc:
            print(f"Error: invalid configuration: {exc}", file=sys.stderr)
            return 1
        try:
            result = export.pack_from_spritesheet(
                args.sheet,
                config,
                out_path,
                sheet_margin=args.margin,
                sheet_spacing=args.spacing,
                sheet_offset=offset,
                write_tsx=args.tsx,
                write_tsj=args.tsj,
            )
        except (OSError, ValueError) as exc:
            print(f"Error: repacking failed: {exc}", file=sys.stderr)
            return 1
        print(
            f"Repacking complete: {result.image_path} "
            f"({result.width}x{result.height}px, "
            f"{result.tile_count} tiles, {result.columns} cols x {result.rows} rows)"
        )
        if result.tsx_path:
            print(f"  .tsx written: {result.tsx_path}")
        if result.tsj_path:
            print(f"  .tsj written: {result.tsj_path}")
        return 0

    # --- (b) Default slice mode -----------------------------------------
    out_dir = args.output_dir
    if not out_dir:
        print("Error: slice mode requires -o/--output-dir.", file=sys.stderr)
        return 1
    try:
        tiles = slicer.slice_sheet(
            args.sheet,
            args.tile_width,
            args.tile_height,
            margin=args.margin,
            spacing=args.spacing,
            offset=offset,
            drop_empty=args.drop_empty,
        )
    except (OSError, ValueError) as exc:
        print(f"Error: slicing failed: {exc}", file=sys.stderr)
        return 1

    os.makedirs(out_dir, exist_ok=True)
    for idx, tile in enumerate(tiles):
        out_path = os.path.join(out_dir, f"tile_{idx:04d}.png")
        tile.save(out_path, "PNG")
    print(f"Slicing complete: saved {len(tiles)} tiles to {out_dir}.")
    return 0


def _cmd_resize(args: argparse.Namespace) -> int:
    """``resize`` subcommand: resize input images to the given size and save them."""
    inputs = expand_inputs(args.inputs)
    if not inputs:
        print("Error: no input images.", file=sys.stderr)
        return 1

    os.makedirs(args.output_dir, exist_ok=True)
    used: set = set()
    count = 0
    for path in inputs:
        try:
            img = imageops.load_image(path)
            resized = imageops.resize_image(
                img,
                (args.tile_width, args.tile_height),
                mode=args.resize_mode,
                resample=args.resample,
                pad_color=args.pad_color,
            )
        except (OSError, ValueError) as exc:
            print(f"Error: failed to process {path}: {exc}", file=sys.stderr)
            return 1
        out_path, collided = _resolve_output_path(args.output_dir, path, used)
        if collided:
            print(
                f"Warning: saving as {os.path.basename(out_path)} to avoid an output name collision (input: {path}).",
                file=sys.stderr,
            )
        resized.save(out_path, "PNG")
        count += 1
    print(f"Resize complete: saved {count} images to {args.output_dir}.")
    return 0


def _cmd_rmbg(args: argparse.Namespace) -> int:
    """``rmbg`` subcommand: remove the background from input images and save them."""
    inputs = expand_inputs(args.inputs)
    if not inputs:
        print("Error: no input images.", file=sys.stderr)
        return 1

    os.makedirs(args.output_dir, exist_ok=True)
    used: set = set()
    count = 0
    for path in inputs:
        try:
            img = imageops.load_image(path)
            cleaned = imageops.remove_background(
                img,
                args.bg_color,
                args.bg_tolerance,
                flood=args.bg_flood,
            )
        except (OSError, ValueError) as exc:
            print(f"Error: failed to process {path}: {exc}", file=sys.stderr)
            return 1
        out_path, collided = _resolve_output_path(args.output_dir, path, used)
        if collided:
            print(
                f"Warning: saving as {os.path.basename(out_path)} to avoid an output name collision (input: {path}).",
                file=sys.stderr,
            )
        cleaned.save(out_path, "PNG")
        count += 1
    print(f"Background removal complete: saved {count} images to {args.output_dir}.")
    return 0


def _estimate_grids(width: int, height: int) -> List[Tuple[int, int, int, int]]:
    """Estimate uniform-grid tile-size candidates that exactly fit the image size.

    Among common square tile sizes, pick those that divide the image's width and
    height evenly, and return them as a list of ``(tile_w, tile_h, cols, rows)``
    candidates.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.

    Returns:
        A list of qualifying ``(tile_w, tile_h, cols, rows)`` candidates (ascending by
        tile size).
    """
    candidates: List[Tuple[int, int, int, int]] = []
    for size in _COMMON_TILE_SIZES:
        if size <= 0 or width <= 0 or height <= 0:
            continue
        if width % size == 0 and height % size == 0:
            cols, rows = slicer.grid_dimensions((width, height), size, size)
            candidates.append((size, size, cols, rows))
    return candidates


def _cmd_info(args: argparse.Namespace) -> int:
    """``info`` subcommand: print each image's size and estimated grid."""
    paths = expand_inputs(args.paths)
    if not paths:
        print("Error: no files to inspect.", file=sys.stderr)
        return 1

    had_error = False
    for path in paths:
        try:
            with Image.open(path) as im:
                width, height = im.size
                mode = im.mode
        except (OSError, ValueError) as exc:
            print(f"{path}: cannot open ({exc})", file=sys.stderr)
            had_error = True
            continue
        print(f"{path}: {width}x{height}px, mode {mode}")
        grids = _estimate_grids(width, height)
        if grids:
            for tw, th, cols, rows in grids:
                print(f"  estimated grid {tw}x{th}: {cols} cols x {rows} rows ({cols * rows} tiles)")
        else:
            print("  estimated grid: no candidate exactly matches a common tile size")

    return 1 if had_error else 0


def _cmd_gui(args: argparse.Namespace) -> int:
    """``gui`` subcommand: launch the GUI."""
    try:
        from tilepacker import gui
    except Exception as exc:  # pragma: no cover - guards against missing gui/dependency
        print(f"Error: cannot load the GUI: {exc}", file=sys.stderr)
        return 1
    return gui.launch()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Parse arguments and run the matching subcommand.

    Args:
        argv: List of command-line arguments. If ``None``, ``sys.argv[1:]`` is used.

    Returns:
        Exit code. 0 on success, 1 on failure (invalid input/processing error).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        return 1

    func = getattr(args, "func", None)
    if func is None:  # pragma: no cover - defensive handling
        parser.print_help(sys.stderr)
        return 1
    return func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
