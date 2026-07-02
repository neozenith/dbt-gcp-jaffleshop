"""Freshness + a per-selector ``dbt ls`` result cache for the sdag viewer.

The invalidation chain is one-directional and designed so a stale result can NEVER be read:

    source files (models / macros / dbt_project.yml / selectors.yml)
        → manifest.json            (reparse only when a source is newer)
            → selector cache       (keyed on manifest+selectors mtime)

* ``manifest_is_fresh`` — true iff ``manifest.json`` is at least as new as every source file,
  so a reparse is needed only when something actually changed.
* The selector cache stores **one JSON file per named selector** under
  ``tmp/adaf_cache/selectors/<selector>.json``. Each file is independently inspectable and
  records the selector's resolved member ``unique_id`` set AND every member's computed
  system-boundary status (``inbound`` / ``outbound`` / ``both`` / ``inner`` — see
  ``adaf.dbt.graph``), alongside a **fingerprint** of ``(manifest mtime, selectors.yml mtime)``.
  On load, a fingerprint mismatch is treated as a miss (``None``) — never a stale hit. Changing
  the manifest or selectors.yml flips the fingerprint, so the cache self-invalidates without any
  explicit bust. One file per selector means a single product can miss/refresh without rewriting
  the others, and the on-disk JSON is a programmatic audit trail of what membership + boundary
  the tool computed.

Cache files live under the project's ``tmp/`` (gitignored), per .claude/rules/caching.md.
"""

# Standard Library
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Source trees/files whose changes can alter the manifest or a selector's membership.
_SOURCE_GLOBS = (
    "models/**/*.sql",
    "models/**/*.yml",
    "models/**/*.yaml",
    "macros/**/*.sql",
    "snapshots/**/*.sql",
    "seeds/**/*.csv",
)
_SOURCE_FILES = ("dbt_project.yml", "selectors.yml", "packages.yml", "package-lock.yml")

# One JSON file per named selector lives under here (each independently inspectable).
_SELECTORS_DIR = Path("tmp") / "adaf_cache" / "selectors"


def _mtime_ns(path: Path) -> int:
    """mtime in ns, or 0 if the path is missing (missing = oldest possible → forces refresh)."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def newest_source_mtime(root: Path) -> int:
    """The newest mtime across every dbt source file under ``root`` (0 if none found)."""
    newest = 0
    for glob in _SOURCE_GLOBS:
        for f in root.glob(glob):
            newest = max(newest, _mtime_ns(f))
    for name in _SOURCE_FILES:
        newest = max(newest, _mtime_ns(root / name))
    return newest


def manifest_is_fresh(manifest: Path, root: Path) -> bool:
    """True iff ``manifest`` exists AND is at least as new as the newest source file.

    When false, a `dbt parse` is warranted; when true, the existing manifest already reflects
    the working tree and reparsing would be wasted work.
    """
    m = _mtime_ns(manifest)
    if m == 0:
        return False
    return m >= newest_source_mtime(root)


def _fingerprint(manifest: Path, selectors: Path) -> str:
    """Identity of the inputs a cached selector result depends on."""
    return f"{_mtime_ns(manifest)}:{_mtime_ns(selectors)}"


@dataclass(frozen=True)
class SelectorCacheEntry:
    """A single named selector's resolved membership plus each member's boundary status.

    ``members`` are the resource ``unique_id``s dbt resolved for the selector; ``boundaries``
    maps each of those ids to its computed system-boundary status (``inbound`` / ``outbound`` /
    ``both`` / ``inner``, from ``adaf.dbt.graph.Graph.classify``). The two are kept together so
    one cache file fully describes a data product.
    """

    members: set[str]
    boundaries: dict[str, str]


def _selector_slug(name: str) -> str:
    """A filesystem-safe stem for a selector name (selector names are usually plain identifiers,
    but a ``/`` or space would break the path — collapse anything outside ``[A-Za-z0-9._-]``)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def selector_cache_path(root: Path, name: str) -> Path:
    """The on-disk path of ``name``'s cache file (exposed so callers can point a human at it)."""
    return root / _SELECTORS_DIR / f"{_selector_slug(name)}.json"


def load_selector(root: Path, manifest: Path, selectors: Path, name: str) -> SelectorCacheEntry | None:
    """Return the cached entry for selector ``name``, or ``None`` if absent/stale/corrupt (a miss).

    A fingerprint mismatch (manifest or selectors.yml changed) yields ``None`` — never a stale read.
    """
    path = selector_cache_path(root, name)
    if not path.exists():
        return None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None  # a corrupt cache file is a miss, not an error
    if blob.get("fingerprint") != _fingerprint(manifest, selectors):
        log.debug("sdag cache: fingerprint mismatch for %s — ignoring stale entry", name)
        return None
    return SelectorCacheEntry(
        members=set(blob.get("members") or []),
        boundaries=dict(blob.get("boundaries") or {}),
    )


def save_selector(root: Path, manifest: Path, selectors: Path, name: str, entry: SelectorCacheEntry) -> Path:
    """Persist one selector's members + boundary annotation, stamped with the current fingerprint.

    The file is written with sorted keys and a ``boundary_counts`` summary so a human (or a script)
    can read it directly and see, at a glance, how many of the product's nodes sit on each boundary.
    """
    path = selector_cache_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = {
        "selector": name,
        "fingerprint": _fingerprint(manifest, selectors),
        "boundary_counts": dict(sorted(Counter(entry.boundaries.values()).items())),
        "members": sorted(entry.members),
        "boundaries": {uid: entry.boundaries[uid] for uid in sorted(entry.boundaries)},
    }
    path.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    log.debug("sdag cache: wrote selector %s (%d members) to %s", name, len(entry.members), path)
    return path
