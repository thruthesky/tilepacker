"""Shared configuration contract for tilepacker.

This module defines :class:`PackConfig`, the single configuration object shared
across the whole package. Every core module (``imageops`` / ``slicer`` /
``packer`` / ``dedup`` / ``tiled`` / ``export``, and so on) operates against
this dataclass's fields as its contract.

Dependencies: standard library only (no Pillow/numpy required).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from typing import Optional, Tuple

__all__ = [
    "RGBA",
    "RESIZE_MODES",
    "RESAMPLE_FILTERS",
    "SORT_MODES",
    "PackConfig",
    "parse_color",
]

#: Type alias for an RGBA color tuple.
RGBA = Tuple[int, int, int, int]

#: Supported resize modes.
#:   none    - no resize (input larger than the cell may be cropped)
#:   stretch - fill the cell exactly, ignoring aspect ratio
#:   fit     - scale to fit inside the cell while keeping aspect ratio, then fill the leftover area with pad_color
#:   cover   - scale to cover the cell while keeping aspect ratio, then center-crop
#:   crop    - no resize; center-crop/pad to the cell size
RESIZE_MODES = frozenset({"none", "stretch", "fit", "cover", "crop"})

#: Pillow resample filter names -> meaning. The actual constant lookup is handled by imageops.parse_resample.
RESAMPLE_FILTERS = frozenset(
    {"nearest", "box", "bilinear", "hamming", "bicubic", "lanczos"}
)

#: Ordering applied to the input tiles.
#:   none    - keep the input order
#:   name    - lexicographic sort by filename
#:   natural - natural sort by filename (tile2 < tile10)
SORT_MODES = frozenset({"none", "name", "natural"})


def parse_color(value) -> Optional[RGBA]:
    """Normalize various color notations into an RGBA 4-tuple.

    Accepted input:
      * ``None`` / ``""`` / ``"none"`` / ``"transparent"`` -> ``None``
      * ``"#rgb"``, ``"#rrggbb"``, ``"#rrggbbaa"`` hex strings
      * ``"r,g,b"`` or ``"r,g,b,a"`` comma-separated strings
      * an integer sequence (tuple/list) of length 3 or 4

    Raises:
        ValueError: when the format cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        comps = [int(c) for c in value]
        if len(comps) == 3:
            comps.append(255)
        if len(comps) != 4:
            raise ValueError(f"color sequence must have 3 or 4 components: {value!r}")
        for c in comps:
            if not 0 <= c <= 255:
                raise ValueError(f"color components must be in the range 0..255: {value!r}")
        return (comps[0], comps[1], comps[2], comps[3])

    s = str(value).strip().lower()
    if s in ("", "none", "transparent", "transparent"):
        return None
    if s.startswith("#"):
        hexpart = s[1:]
        if len(hexpart) == 3:
            r, g, b = (int(ch * 2, 16) for ch in hexpart)
            return (r, g, b, 255)
        if len(hexpart) == 6:
            r = int(hexpart[0:2], 16)
            g = int(hexpart[2:4], 16)
            b = int(hexpart[4:6], 16)
            return (r, g, b, 255)
        if len(hexpart) == 8:
            r = int(hexpart[0:2], 16)
            g = int(hexpart[2:4], 16)
            b = int(hexpart[4:6], 16)
            a = int(hexpart[6:8], 16)
            return (r, g, b, a)
        raise ValueError(f"hex color must be in #rgb/#rrggbb/#rrggbbaa format: {value!r}")
    if "," in s:
        parts = [int(p) for p in s.split(",")]
        return parse_color(parts)
    raise ValueError(f"could not parse color: {value!r}")


@dataclass
class PackConfig:
    """Configuration object that controls the entire tileset packing pipeline.

    It is the single source of truth shared by every core module. The fields
    fall into five broad groups: (1) grid geometry, (2) cell processing,
    (3) background removal / trim preprocessing, (4) postprocessing / sorting,
    and (5) metadata.
    """

    # --- (1) grid geometry ----------------------------------------------
    tile_width: int = 32          # cell width (px)
    tile_height: int = 32         # cell height (px)
    columns: int = 0              # number of tileset columns; 0 means auto (close to square)
    margin: int = 0               # outer border margin of the tileset (px)
    spacing: int = 0              # spacing between tiles (px)
    extrude: int = 0              # preventTearing: extend each tile's edges outward by N px

    # --- (2) cell processing --------------------------------------------
    resize_mode: str = "fit"      # one of RESIZE_MODES
    resample: str = "nearest"     # one of RESAMPLE_FILTERS (nearest by default for pixel art)
    pad_color: Optional[RGBA] = None   # color of the leftover area in fit mode (None=transparent)
    background: Optional[RGBA] = None  # base background of each cell (None=transparent)

    # --- (3) background removal / trim preprocessing --------------------
    bg_remove: bool = False       # enable background removal
    bg_color: Optional[RGBA] = None    # background color to remove (None=auto-sample the four corners)
    bg_tolerance: int = 0         # color distance tolerance (0..441)
    bg_flood: bool = False        # True=flood fill from the corners, False=global color matching
    trim: bool = False            # auto-remove transparent borders per tile

    # --- (4) postprocessing / sorting -----------------------------------
    sort: str = "none"            # one of SORT_MODES
    deduplicate: bool = False     # remove duplicate tiles with identical pixels
    drop_empty: bool = False      # remove fully transparent tiles

    # --- (5) metadata ---------------------------------------------------
    name: str = "tileset"         # tileset name (the name attribute in .tsx / default output filename)

    # ------------------------------------------------------------------
    def validate(self) -> None:
        """Check that the configuration is consistent. Raises ``ValueError`` on a problem."""
        if self.tile_width <= 0 or self.tile_height <= 0:
            raise ValueError("tile_width/tile_height must be positive.")
        for attr in ("columns", "margin", "spacing", "extrude", "bg_tolerance"):
            if getattr(self, attr) < 0:
                raise ValueError(f"{attr} cannot be negative.")
        if self.resize_mode not in RESIZE_MODES:
            raise ValueError(
                f"resize_mode must be one of {sorted(RESIZE_MODES)}: {self.resize_mode!r}"
            )
        if self.resample not in RESAMPLE_FILTERS:
            raise ValueError(
                f"resample must be one of {sorted(RESAMPLE_FILTERS)}: {self.resample!r}"
            )
        if self.sort not in SORT_MODES:
            raise ValueError(
                f"sort must be one of {sorted(SORT_MODES)}: {self.sort!r}"
            )
        if self.bg_tolerance > 441:
            raise ValueError("bg_tolerance must be in the range 0..441 (max RGB Euclidean distance).")

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict (color tuples become lists)."""
        d = asdict(self)
        for key in ("pad_color", "background", "bg_color"):
            if d[key] is not None:
                d[key] = list(d[key])
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "PackConfig":
        """Build a configuration object from a dict (e.g. the result of a JSON load).

        Unknown keys are ignored, and color fields are normalized with :func:`parse_color`.
        """
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        for key in ("pad_color", "background", "bg_color"):
            if key in kwargs:
                kwargs[key] = parse_color(kwargs[key])
        cfg = cls(**kwargs)
        cfg.validate()
        return cfg

    def copy(self, **overrides) -> "PackConfig":
        """Return a copy with only some fields overridden."""
        data = asdict(self)
        data.update(overrides)
        return PackConfig(**data)
