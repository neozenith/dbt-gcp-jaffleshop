"""Load + resolve a ``.adaf.yml`` config that disables lint rule IDs per file/folder.

A human-curated false-positive allowlist for the sdag boundary checks: each entry names a
rule ID (or ``*`` for all rules) and a set of project-relative path globs, plus an optional
reason. A finding is suppressed when some entry's rule matches AND one of its path globs
matches the model's project-relative path.

``.adaf.yml`` schema::

    suppress:
      - rule: MD-02                      # a lint rule ID, or '*' for all rules
        paths: ["models/legacy/**", "models/x/foo.sql"]
        reason: "grandfathered; ticket DTB-1234"   # optional, for humans
      - rule: "*"
        paths: ["models/scratch/**"]

Globbing is pathspec-style: ``*`` matches within a path segment, ``**`` spans directories.
A missing file means no suppressions (empty). ruamel.yaml parses the file so other tooling
can round-trip the same config (comments + ordering preserved). See dbt/selectors.py for the
ruamel idiom.
"""

# Standard Library
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# Third Party
from ruamel.yaml import YAML

_yaml = YAML()

# Repo-root default config location. Another task wires this into config.py.
DEFAULT_ADAF_CONFIG = Path(".adaf.yml")


def _glob_matches(pattern: str, model_path: str) -> bool:
    """True if ``model_path`` matches a pathspec-style ``pattern`` (``**`` spans directories)."""
    path = PurePosixPath(model_path)
    if "**" not in pattern:
        return path.match(pattern)
    # PurePath.match doesn't understand '**', so expand the prefix-before-'**' literally and
    # let the remaining tail match any descendant.
    head, _, tail = pattern.partition("**")
    head = head.rstrip("/")
    norm = model_path
    if head:
        if not (norm == head or norm.startswith(head + "/")):
            return False
        norm = norm[len(head) :].lstrip("/")
    tail = tail.lstrip("/")
    if not tail:
        return True  # '<head>/**' matches everything beneath head
    # Match the tail against the path itself and every suffix (so '**/foo.sql' hits any depth).
    parts = norm.split("/")
    return any(PurePosixPath("/".join(parts[i:])).match(tail) for i in range(len(parts)))


@dataclass(frozen=True)
class _Entry:
    """One ``suppress`` entry: a rule ID (or ``*``) plus its path globs."""

    rule: str
    paths: tuple[str, ...]
    reason: str = ""

    def matches(self, rule_id: str, model_path: str) -> bool:
        if self.rule != "*" and self.rule != rule_id:
            return False
        return any(_glob_matches(p, model_path) for p in self.paths)


@dataclass(frozen=True)
class Suppressions:
    """Resolved ``.adaf.yml`` suppressions — query with :meth:`is_suppressed`."""

    entries: tuple[_Entry, ...] = field(default_factory=tuple)

    def is_suppressed(self, rule_id: str, model_path: str) -> bool:
        """True if any entry suppresses ``rule_id`` for the project-relative ``model_path``."""
        return any(e.matches(rule_id, model_path) for e in self.entries)


def load_suppressions(path: Path) -> Suppressions:
    """Read ``.adaf.yml`` → :class:`Suppressions`. Missing file means no suppressions (empty)."""
    if not path.exists():
        return Suppressions()
    data = _yaml.load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("suppress") or []
    if not isinstance(raw, list):
        raise ValueError(f"{path}: top-level `suppress` must be a list, got {type(raw).__name__}")
    entries: list[_Entry] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"{path}: each suppress entry must be a mapping, got {item!r}")
        rule = item.get("rule")
        if not rule:
            raise ValueError(f"{path}: suppress entry missing `rule`: {item!r}")
        paths = item.get("paths") or []
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ValueError(f"{path}: suppress entry `paths` must be a list of strings: {item!r}")
        entries.append(_Entry(str(rule), tuple(paths), str(item.get("reason") or "").strip()))
    return Suppressions(tuple(entries))
