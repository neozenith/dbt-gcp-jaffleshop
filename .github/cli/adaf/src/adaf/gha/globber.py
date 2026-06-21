"""Collapse a selector's discovered model files into `on.pull_request.paths` trigger globs.

Three modes, increasingly aggressive (and increasingly over-matching):

* ``strict``    — list every discovered ``.sql`` file verbatim. Zero false positives; longest list.
* ``leaf``      — collapse only the filename: one ``<dir>/*.{sql,yml}`` per directory. Catches the
                  models' schema YAML siblings; over-matches other files in the same dirs.
* ``recursive`` — (default) further collapse directories that differ in a single path component into a
                  ``**`` wildcard (``models/cdm/demand`` + ``models/marts/demand`` ⇒ ``models/**/demand``)
                  and recurse with a trailing ``/**``. Shortest list; widest over-match.

A GitHub path filter that OVER-matches only over-triggers CI (harmless); one that UNDER-matches misses a
changed model (unsafe). Every mode here is over-match-safe: the emitted globs always cover the full
discovered set. :func:`false_positives` quantifies the over-match against the canonical strict list so a
human can judge a mode before committing it.
"""

# Standard Library
import re
from itertools import combinations
from pathlib import Path

# Local
from adaf import report

PATH_MODES = ("strict", "leaf", "recursive")
DEFAULT_PATH_MODE = "recursive"

_LEAF_GLOB = "*.{sql,yml}"  # filename collapsed to "any sql/yml in this dir"


def _dirs(paths: set[str]) -> set[tuple[str, ...]]:
    """Unique parent directories of ``paths`` as component tuples (``models/marts/fct.sql`` → marts dir)."""
    return {tuple(p.split("/")[:-1]) for p in paths if "/" in p}


def _wildcard_merge(dirs: set[tuple[str, ...]]) -> set[tuple[str, ...]]:
    """Merge dirs of equal depth that differ in exactly one component into a ``**`` at that position.

    Repeated to a fixpoint, so ``{(models,cdm,demand),(models,marts,demand)}`` →
    ``{(models,**,demand)}``. Over-merging is trigger-safe (it only widens the match)."""
    cur = set(dirs)
    changed = True
    while changed:
        changed = False
        for a, b in combinations(sorted(cur), 2):
            if len(a) != len(b):
                continue
            diffs = [i for i in range(len(a)) if a[i] != b[i]]
            if len(diffs) == 1 and "**" not in (a[diffs[0]], b[diffs[0]]):
                merged = tuple("**" if i == diffs[0] else a[i] for i in range(len(a)))
                cur.discard(a)
                cur.discard(b)
                cur.add(merged)
                changed = True
                break
    return cur


def _covers(prefix: tuple[str, ...], other: tuple[str, ...]) -> bool:
    """True if ``prefix`` (as a ``prefix/**`` glob) subsumes ``other`` — ``**`` matches any component."""
    if len(prefix) > len(other) or prefix == other:
        return False
    return all(pc == "**" or pc == oc for pc, oc in zip(prefix, other, strict=False))


def _subsume(dirs: set[tuple[str, ...]]) -> set[tuple[str, ...]]:
    """Drop any dir already covered by a shorter ``prefix/**`` glob in the set."""
    return {d for d in dirs if not any(_covers(other, d) for other in dirs if other != d)}


def discover_to_globs(paths: set[str], mode: str) -> list[str]:
    """Discovered ``.sql`` paths → sorted trigger globs (mode-dependent). Caller appends static paths
    like ``dbt_project.yml``. Raises on an unknown mode (no silent fallback)."""
    if mode not in PATH_MODES:
        raise ValueError(f"unknown --paths mode '{mode}' (choose from {', '.join(PATH_MODES)})")
    if mode == "strict":
        return sorted(paths)
    if mode == "leaf":
        return sorted(f"{'/'.join(d)}/{_LEAF_GLOB}" for d in _dirs(paths))
    collapsed = _subsume(_wildcard_merge(_dirs(paths)))
    return sorted(f"{'/'.join(d)}/**" for d in collapsed)


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a GitHub-style path glob (``**``, ``*``, ``{a,b}``) to an anchored regex for matching."""
    out = ["^"]
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")  # zero or more leading dirs
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "{":
            j = pattern.index("}", i)
            alts = pattern[i + 1 : j].split(",")
            out.append("(?:" + "|".join(re.escape(a) for a in alts) + ")")
            i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def universe_sql(root: Path, *, with_macros: bool) -> set[str]:
    """Every ``.sql`` under ``models/`` (and ``macros/`` when ``with_macros``) as project-relative
    paths — the comparison set the false-positive audit measures globs against."""
    dirs = ["models", "macros"] if with_macros else ["models"]
    return {str(p.relative_to(root)) for d in dirs if (root / d).is_dir() for p in (root / d).rglob("*.sql")}


def false_positives(globs: list[str], universe: set[str], canonical: set[str]) -> set[str]:
    """Files in ``universe`` matched by ``globs`` but NOT in ``canonical`` (the strict discovered set).

    ``universe`` should be the comparable file set (e.g. every ``.sql`` under the project), so the result
    is the *other* models a mode's globs would also trigger on — the cost of collapsing."""
    regexes = [glob_to_regex(g) for g in globs]
    matched = {f for f in universe if any(rx.match(f) for rx in regexes)}
    return matched - canonical


def render_working_out(
    product: str, mode: str, paths: set[str], globs: list[str], fps: set[str], *, color: bool = False
) -> str:
    """Human-readable derivation: discovered count → emitted globs → false-positive audit.

    Colours follow the shared report palette: the ``#`` headline is info (cyan) and the
    false-positive audit is painted ``darkred`` — the same hue ``adaf list --paths`` uses to
    highlight over-matched files — while a clean audit reads ``ok`` (green).
    """
    lines = [
        report.colorize(f"# paths working-out — product '{product}' (--paths {mode})", "cyan", color),
        f"discovered {len(paths)} model file(s); collapsed to {len(globs)} glob(s):",
        *(f"  + {g}" for g in globs),
    ]
    if fps:
        header = f"false positives ({len(fps)} file(s) matched by the globs but NOT in the selector):"
        lines.append(report.colorize(header, "darkred", color))
        lines += [report.colorize(f"  ! {f}", "darkred", color) for f in sorted(fps)[:20]]
        if len(fps) > 20:
            lines.append(f"  … and {len(fps) - 20} more")
    else:
        lines.append(
            report.colorize("false positives: none (globs match exactly the discovered files)", "green", color)
        )
    return "\n".join(lines)
