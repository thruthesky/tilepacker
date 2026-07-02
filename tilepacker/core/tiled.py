"""Tileset definition file generator for the Tiled map editor.

This module builds a Tiled 1.x-compatible tileset definition file, as a string,
that points to a packed tileset PNG, and writes it to disk when needed. Two
formats are supported.

* ``.tsx`` : XML-based external tileset definition (Tiled's traditional format)
* ``.tsj`` : JSON-based external tileset definition

It uses only the standard library (``xml.sax.saxutils``, ``json``) and does not
depend on Pillow/numpy. It can therefore generate just the metadata,
independently of the image-processing pipeline.
"""

from __future__ import annotations

import json
import os
from typing import Optional, Union
from xml.sax.saxutils import quoteattr

__all__ = [
    "build_tsx",
    "build_tsj",
    "build_tmx",
    "write_tsx",
    "write_tsj",
    "write_tmx",
]


def build_tsx(
    *,
    name: str,
    image_source: str,
    image_width: int,
    image_height: int,
    tile_width: int,
    tile_height: int,
    tile_count: int,
    columns: int,
    margin: int = 0,
    spacing: int = 0,
    version: str = "1.10",
    tiled_version: str = "1.10.2",
    grid_orientation: Optional[str] = None,
    grid_width: int = 0,
    grid_height: int = 0,
) -> str:
    """Build a Tiled 1.x-compatible ``.tsx`` (XML) tileset definition string.

    Args:
        name: The tileset name (``<tileset name=...>``).
        image_source: The tileset image file path (usually relative to the .tsx file).
        image_width: The horizontal pixel count of the tileset image.
        image_height: The vertical pixel count of the tileset image.
        tile_width: The horizontal pixel count of a single tile (cell).
        tile_height: The vertical pixel count of a single tile (cell).
        tile_count: The total number of tiles in the tileset.
        columns: The number of columns in the tileset.
        margin: The outer border padding of the tileset (px). The attribute is omitted when 0.
        spacing: The gap between tiles (px). The attribute is omitted when 0.
        version: The Tiled map format version string.
        tiled_version: The version string of the Tiled editor that generated this file.
        grid_orientation: Tile grid orientation (``"isometric"`` or ``"orthogonal"``).
            When set, a ``<grid>`` child element is emitted; ``None`` omits it
            (Tiled then assumes orthogonal). Used for isometric tilesets.
        grid_width: The grid cell width for the ``<grid>`` element (px).
        grid_height: The grid cell height for the ``<grid>`` element (px).

    Returns:
        An XML string, indented for readability, that starts with an
        ``<?xml ...?>`` declaration and has ``<tileset>`` as its root.

    Notes:
        The attribute order follows the convention that Tiled emits:
        version, tiledversion, name, tilewidth, tileheight,
        (spacing>0), (margin>0), tilecount, columns.
        The optional ``<grid>`` element precedes the ``<image>`` child, which
        has source, width, and height attributes.
    """
    # Accumulate the root <tileset> attributes as (key, value) pairs in the specified order.
    attrs: list[tuple[str, str]] = [
        ("version", str(version)),
        ("tiledversion", str(tiled_version)),
        ("name", str(name)),
        ("tilewidth", str(int(tile_width))),
        ("tileheight", str(int(tile_height))),
    ]
    if int(spacing) > 0:
        attrs.append(("spacing", str(int(spacing))))
    if int(margin) > 0:
        attrs.append(("margin", str(int(margin))))
    attrs.append(("tilecount", str(int(tile_count))))
    attrs.append(("columns", str(int(columns))))

    # quoteattr safely wraps values in quotes and escapes XML special characters.
    tileset_attrs = " ".join(f"{k}={quoteattr(v)}" for k, v in attrs)

    image_attrs = " ".join(
        f"{k}={quoteattr(v)}"
        for k, v in (
            ("source", str(image_source)),
            ("width", str(int(image_width))),
            ("height", str(int(image_height))),
        )
    )

    children: list[str] = []
    if grid_orientation:
        grid_attrs = " ".join(
            f"{k}={quoteattr(v)}"
            for k, v in (
                ("orientation", str(grid_orientation)),
                ("width", str(int(grid_width))),
                ("height", str(int(grid_height))),
            )
        )
        children.append(f" <grid {grid_attrs}/>")
    children.append(f" <image {image_attrs}/>")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<tileset {tileset_attrs}>",
        *children,
        "</tileset>",
        "",
    ]
    return "\n".join(lines)


def build_tsj(
    *,
    name: str,
    image_source: str,
    image_width: int,
    image_height: int,
    tile_width: int,
    tile_height: int,
    tile_count: int,
    columns: int,
    margin: int = 0,
    spacing: int = 0,
    version: str = "1.10",
    tiled_version: str = "1.10.2",
    grid_orientation: Optional[str] = None,
    grid_width: int = 0,
    grid_height: int = 0,
) -> str:
    """Build a Tiled JSON tileset (``.tsj``) format string.

    Args:
        name: The tileset name.
        image_source: The tileset image file path.
        image_width: The horizontal pixel count of the tileset image.
        image_height: The vertical pixel count of the tileset image.
        tile_width: The horizontal pixel count of a single tile (cell).
        tile_height: The vertical pixel count of a single tile (cell).
        tile_count: The total number of tiles in the tileset.
        columns: The number of columns in the tileset.
        margin: The outer border padding of the tileset (px).
        spacing: The gap between tiles (px).
        version: The Tiled map format version string.
        tiled_version: The version string of the Tiled editor that generated this file.

    Returns:
        A string serializing the Tiled JSON tileset object via
        ``json.dumps(indent=2)``. Keys are sorted in dictionary order and
        ``type`` is always ``"tileset"``.
    """
    data = {
        "columns": int(columns),
        "image": str(image_source),
        "imageheight": int(image_height),
        "imagewidth": int(image_width),
        "margin": int(margin),
        "name": str(name),
        "spacing": int(spacing),
        "tilecount": int(tile_count),
        "tiledversion": str(tiled_version),
        "tileheight": int(tile_height),
        "tilewidth": int(tile_width),
        "type": "tileset",
        "version": str(version),
    }
    if grid_orientation:
        data["grid"] = {
            "orientation": str(grid_orientation),
            "width": int(grid_width),
            "height": int(grid_height),
        }
    return json.dumps(data, indent=2, ensure_ascii=False)


def build_tmx(
    *,
    tileset_source: str,
    columns: int,
    rows: int,
    tile_width: int,
    tile_height: int,
    gids,
    orientation: str = "isometric",
    layer_name: str = "Tile Layer 1",
    firstgid: int = 1,
) -> str:
    """Build a Tiled ``.tmx`` map (XML) that places tiles on a grid.

    This lets a packed tileset be opened in Tiled with its original layout
    intact instead of an empty palette the user must re-stamp.

    Args:
        tileset_source: The ``.tsx`` filename the map references (basename).
        columns: Map width in tiles.
        rows: Map height in tiles.
        tile_width: Tile (cell) width in px.
        tile_height: Tile (cell) height in px.
        gids: A ``rows`` x ``columns`` sequence of global tile ids; ``0`` means
            an empty cell. A tile placed from local id ``i`` (row-major in the
            tileset) uses ``firstgid + i``.
        orientation: Map orientation (``"isometric"`` by default).
        layer_name: The tile layer's name.
        firstgid: The tileset's first global id (usually ``1``).

    Returns:
        The ``.tmx`` XML as a string.
    """
    cols = int(columns)
    rws = int(rows)
    # CSV data: comma-separated gids, one map row per text line. A trailing comma
    # ends every line except the last (Tiled's canonical CSV layout).
    lines = []
    for r in range(rws):
        row_vals = ",".join(str(int(gids[r][c])) for c in range(cols))
        if r < rws - 1:
            row_vals += ","
        lines.append(row_vals)
    csv = "\n".join(lines)

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<map version="1.10" tiledversion="1.10.2" orientation="{orientation}" '
        f'renderorder="right-down" width="{cols}" height="{rws}" '
        f'tilewidth="{int(tile_width)}" tileheight="{int(tile_height)}" '
        'infinite="0" nextlayerid="2" nextobjectid="1">\n'
        f' <tileset firstgid="{int(firstgid)}" source="{tileset_source}"/>\n'
        f' <layer id="1" name="{layer_name}" width="{cols}" height="{rws}">\n'
        '  <data encoding="csv">\n'
        f"{csv}\n"
        "</data>\n"
        " </layer>\n"
        "</map>\n"
    )


def write_tsx(path: Union[str, "os.PathLike"], **kwargs) -> str:
    """Write the :func:`build_tsx` result to a file as UTF-8 and return that string.

    Args:
        path: The ``.tsx`` file path to write.
        **kwargs: Keyword arguments passed through to :func:`build_tsx`.

    Returns:
        The XML string written to the file.
    """
    text = build_tsx(**kwargs)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)
    return text


def write_tsj(path: Union[str, "os.PathLike"], **kwargs) -> str:
    """Write the :func:`build_tsj` result to a file as UTF-8 and return that string.

    Args:
        path: The ``.tsj`` file path to write.
        **kwargs: Keyword arguments passed through to :func:`build_tsj`.

    Returns:
        The JSON string written to the file.
    """
    text = build_tsj(**kwargs)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)
    return text


def write_tmx(path: Union[str, "os.PathLike"], **kwargs) -> str:
    """Write the :func:`build_tmx` result to a file as UTF-8 and return that string.

    Args:
        path: The ``.tmx`` file path to write.
        **kwargs: Keyword arguments passed through to :func:`build_tmx`.

    Returns:
        The XML string written to the file.
    """
    text = build_tmx(**kwargs)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)
    return text
