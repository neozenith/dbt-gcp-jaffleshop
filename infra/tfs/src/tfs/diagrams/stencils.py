"""Load the vendored stencil asset (``assets/stencils.json.zip``).

The full provider palette is ~6 MB of JSON, so the version-controlled artifact is
a DEFLATE zip; this loader unarchives it in memory on first use (no temp files).
Shipped as package data and read via importlib.resources (the same mechanism
``commands/create.py`` uses for templates), so it works installed or from source.
Each entry: ``{w, h, svg, stencil_b64}`` keyed by ``"<library>/<shape>"``.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

_ZIP = "stencils.json.zip"
_ARCNAME = "stencils.json"


@dataclass(frozen=True)
class Stencil:
    w: float
    h: float
    svg: str  # inner SVG fragment in the stencil's own 0..w/0..h coords; uses currentColor
    stencil_b64: str  # draw.io shape=stencil(...) payload (deflate+base64 of the <shape> xml)


@cache
def _load() -> dict[str, Stencil]:
    data = (files("tfs") / "assets" / _ZIP).read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        raw = json.loads(zf.read(_ARCNAME))
    return {k: Stencil(v["w"], v["h"], v["svg"], v["stencil_b64"]) for k, v in raw.items()}


def get(stencil_id: str | None) -> Stencil | None:
    if stencil_id is None:
        return None
    return _load().get(stencil_id)
