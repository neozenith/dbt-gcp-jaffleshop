"""Layered rule suppression — manage false positives like a linter.

Two layers, both citing a rule code from the catalogue:

1. **Config globs** — ``adaf.yml`` at the project root maps path globs to disabled rule codes,
   for per-folder / per-file opt-outs::

       disable:
         - rules: [MD-02]
           paths: ["models/marts/metricflow_time_spine.sql"]
           reason: "generated spine — a contract adds no value"

2. **Inline comments** — a comment in a model's ``.sql`` disables a rule for THAT file::

       -- adaf-disable: MD-01 (spine has no natural grain to test)
       -- adaf-disable-file: MD-02, MD-01    (the -file suffix is an accepted synonym)

A reason is encouraged (it is what a reviewer reads); the engine records it. Suppressions are
filtered out of the deterministic findings AND fed to the LLM review prompt so it won't re-flag
them. ``adaf rules explain <CODE>`` prints both forms verbatim, so the tooling teaches its own
escape hatch. Suppressing a rule is auditable: every drop is counted and, with ``--show-passes``,
listed with its reason.
"""

import logging
import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

CONFIG_NAME = "adaf.yml"

# `-- adaf-disable: CODE[, CODE...] (optional reason)`  (the `-file` suffix is an accepted synonym).
_INLINE_RE = re.compile(
    r"--\s*adaf-disable(?:-file)?\s*:\s*([A-Za-z0-9,\s-]+?)\s*(?:\(([^)]*)\))?\s*$",
    re.IGNORECASE,
)
_CODE_RE = re.compile(r"\b([A-Z]{2}(?:-[A-Z]{2})?-\d{2})\b")


@dataclass(frozen=True)
class SuppressionRule:
    """One config-level rule: disable these codes on files matching any of these globs."""

    codes: frozenset[str]
    paths: tuple[str, ...]
    reason: str

    def matches(self, rule_code: str, rel_path: str) -> bool:
        return rule_code in self.codes and any(fnmatch(rel_path, g) for g in self.paths)


@dataclass
class Suppressions:
    """Resolved suppressions for a project: config globs + lazily-scanned inline comments."""

    project_root: Path
    config_rules: list[SuppressionRule] = field(default_factory=list)
    _inline_cache: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def load(cls, project_root: Path) -> "Suppressions":
        """Read ``adaf.yml`` from the project root (absent file → no config suppressions)."""
        cfg = project_root / CONFIG_NAME
        rules: list[SuppressionRule] = []
        if cfg.exists():
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            for entry in data.get("disable") or []:
                codes = frozenset(c.strip().upper() for c in (entry.get("rules") or []))
                paths = tuple(entry.get("paths") or [])
                if codes and paths:
                    rules.append(SuppressionRule(codes, paths, (entry.get("reason") or "").strip()))
        return cls(project_root, rules)

    def _inline_for(self, rel_path: str) -> dict[str, str]:
        """{rule_code: reason} parsed from a model file's ``-- adaf-disable`` comments (cached)."""
        if rel_path in self._inline_cache:
            return self._inline_cache[rel_path]
        found: dict[str, str] = {}
        path = self.project_root / rel_path
        if path.suffix == ".sql" and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                m = _INLINE_RE.search(line)
                if not m:
                    continue
                reason = (m.group(2) or "").strip()
                for code in _CODE_RE.findall(m.group(1).upper()):
                    found[code] = reason
        self._inline_cache[rel_path] = found
        return found

    def reason_for(self, rule_code: str, rel_path: str) -> str | None:
        """The suppression reason if ``rule_code`` is disabled for ``rel_path``, else None.

        Config globs win first; then the file's own inline comments. Returns a (possibly empty)
        reason string when suppressed, ``None`` when not.
        """
        for rule in self.config_rules:
            if rule.matches(rule_code, rel_path):
                return rule.reason or f"{CONFIG_NAME} glob"
        inline = self._inline_for(rel_path)
        if rule_code in inline:
            return inline[rule_code] or "inline -- adaf-disable"
        return None

    def is_suppressed(self, rule_code: str, rel_path: str) -> bool:
        return self.reason_for(rule_code, rel_path) is not None


def disable_help(rule_code: str) -> list[str]:
    """The exact 'how to disable this' lines — shown by every warning and by ``rules explain``."""
    return [
        f"To suppress {rule_code} (e.g. a false positive), either:",
        f"  • inline in the model's .sql:   -- adaf-disable: {rule_code} (why it doesn't apply here)",
        f"  • or in {CONFIG_NAME} at the project root:",
        "        disable:",
        f"          - rules: [{rule_code}]",
        '            paths: ["models/path/glob/**"]',
        '            reason: "why this rule is a false positive here"',
    ]
