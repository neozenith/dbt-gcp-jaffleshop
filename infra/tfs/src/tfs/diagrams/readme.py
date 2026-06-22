"""Embed a stack's architecture diagram into its README — `tfs diagram <stack> --readme`.

Renders the canonical (prod, state) architecture SVG into the stack directory and
upserts a sticky, marker-delimited region in the stack's ``README.md``. Same
sticky-marker idea as the PR comment in :mod:`tfs.diagrams.publish`, but the target
is a committed file instead of a GitHub comment.

Everything here is a pure string/bytes function (no terraform, no IO), so it is
fully unit-testable; the plan/render/file IO orchestration lives in
:mod:`tfs.diagrams.command`.
"""

from __future__ import annotations

# Sticky region delimiters. One region per README (the README is per-stack), so —
# unlike publish.marker — these need no stack suffix.
MARKER_START = "<!-- tf-diagram:start -->"
MARKER_END = "<!-- tf-diagram:end -->"

# The committed SVG lives beside the README; the embed references it relatively.
SVG_FILENAME = "architecture.svg"


def embed_block(stack: str, env: str, svg_relpath: str = SVG_FILENAME) -> str:
    """The marker-delimited markdown region embedding the architecture SVG.

    Deliberately carries NO timestamp/sha: the region must be a pure function of its
    inputs so that re-rendering an unchanged stack reproduces it byte-for-byte. That
    determinism is what lets ``--check`` act as a stable fitness function.
    """
    return "\n".join(
        [
            MARKER_START,
            "## Architecture",
            "",
            f"_Generated from the `{env}` plan by `tfs diagram {stack} --readme` — "
            "do not edit by hand; re-run that command to refresh._",
            "",
            f"![{stack} architecture ({env})]({svg_relpath})",
            MARKER_END,
        ]
    )


def upsert_region(readme_text: str, block: str) -> str:
    """Replace the marked region with ``block``, or append it if absent. Idempotent.

    Appending preserves a single trailing newline so re-running ``upsert_region`` on
    its own output is a no-op (the staleness check relies on this fixed point).
    """
    start = readme_text.find(MARKER_START)
    end = readme_text.find(MARKER_END)
    if start != -1 and end != -1 and end > start:
        end += len(MARKER_END)
        return readme_text[:start] + block + readme_text[end:]
    if not readme_text:
        return f"{block}\n"
    sep = "\n" if readme_text.endswith("\n") else "\n\n"
    return f"{readme_text}{sep}{block}\n"


def staleness(readme_text: str, block: str, committed_svg: bytes | None, fresh_svg: bytes) -> list[str]:
    """Reasons the committed README/SVG diverge from a fresh render (empty list = fresh).

    Used by ``--check``: a non-empty list means the developer changed the stack but
    didn't re-run ``tfs diagram <stack> --readme``.
    """
    reasons: list[str] = []
    if committed_svg is None:
        reasons.append(f"{SVG_FILENAME} is missing")
    elif committed_svg != fresh_svg:
        reasons.append(f"{SVG_FILENAME} is out of date")
    if upsert_region(readme_text, block) != readme_text:
        reasons.append("README.md diagram region is missing or out of date")
    return reasons


def lint(readme_text: str, svg_exists: bool, svg_parses: bool) -> list[str]:
    """Cheap, auth-free structural check (no rendering): markers present and paired,
    referenced SVG exists and parses. Catches a hand-mangled region without needing
    a terraform plan. Returns problems (empty list = well-formed)."""
    problems: list[str] = []
    start, end = readme_text.find(MARKER_START), readme_text.find(MARKER_END)
    if start == -1 or end == -1:
        problems.append("README.md is missing the tf-diagram markers (run `tfs diagram <stack> --readme`)")
    elif end < start:
        problems.append("README.md tf-diagram markers are out of order")
    if not svg_exists:
        problems.append(f"{SVG_FILENAME} referenced by the README does not exist")
    elif not svg_parses:
        problems.append(f"{SVG_FILENAME} is not valid XML/SVG")
    return problems
