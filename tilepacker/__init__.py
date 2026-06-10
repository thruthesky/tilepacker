"""tilepacker — a package that packs individual tile images into a uniform grid tileset for Tiled.

This package takes individual tile PNGs (or a spritesheet) and runs them through
resizing, background removal, grid slicing, extrusion (preventTearing), and
duplicate/empty tile removal to produce a single uniform grid tileset PNG along
with the matching Tiled ``.tsx`` / ``.tsj`` definition files.

Quick usage example::

    from tilepacker import PackConfig, pack_from_files

    cfg = PackConfig(tile_width=16, tile_height=16, name="terrain")
    result = pack_from_files(
        ["a.png", "b.png", "c.png"],
        cfg,
        "out/terrain.png",
        write_tsx=True,
    )
    print(result.image_path, result.tsx_path, result.tile_count)
"""

from __future__ import annotations

__version__ = "0.1.0"

from tilepacker.core.config import PackConfig, parse_color
from tilepacker.core.export import (
    ExportResult,
    export_tileset,
    pack_from_files,
    pack_from_spritesheet,
)
from tilepacker.core.packer import PackedTileset, pack_tiles
from tilepacker.core.imageops import (
    extrude_edges,
    load_image,
    remove_background,
    resize_image,
    trim,
)
from tilepacker.core.slicer import slice_image, slice_sheet
from tilepacker.core.dedup import deduplicate

__all__ = [
    "__version__",
    # config
    "PackConfig",
    "parse_color",
    # export
    "export_tileset",
    "pack_from_files",
    "pack_from_spritesheet",
    "ExportResult",
    # packer
    "pack_tiles",
    "PackedTileset",
    # imageops
    "resize_image",
    "remove_background",
    "trim",
    "extrude_edges",
    "load_image",
    # slicer
    "slice_image",
    "slice_sheet",
    # dedup
    "deduplicate",
]
