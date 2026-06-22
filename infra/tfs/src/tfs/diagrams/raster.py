"""SVG -> PNG rasterization via cairosvg.

cairosvg needs the system cairo library (``brew install cairo`` /
``apt-get install libcairo2``). Missing it is a hard, loud failure — the PNG is a
real requirement, not optional. cairosvg is imported lazily inside the call so the
module stays importable (and `tfs diagram --help` works) where cairo is absent;
the rasterize call itself crashes clearly if the library is missing.
"""

from __future__ import annotations

from pathlib import Path


def svg_to_png(svg_path: Path, png_path: Path, *, scale: float = 2.0) -> None:
    import cairosvg  # pragma: no cover - cairo binding IO (needs system libcairo)

    cairosvg.svg2png(  # pragma: no cover
        url=str(svg_path),
        write_to=str(png_path),
        scale=scale,
        background_color="white",
    )
