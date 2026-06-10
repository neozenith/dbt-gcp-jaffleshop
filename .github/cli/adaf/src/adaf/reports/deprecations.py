"""Result dataclass for ``check deprecations`` (dbt-autofix)."""

import logging
from dataclasses import dataclass, field

from adaf.utils import style
from adaf.utils.toollog import ToolLog

INFO = logging.INFO
ERROR = logging.ERROR


@dataclass
class DeprecationsReport:
    name = "deprecations"
    mode: str  # "check" or "fix"
    scope: str
    scanned_dirs: list[str]
    records: list[dict]
    logs: list[ToolLog] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # In fix mode the tool succeeded (errors raise), so applying changes is success.
        return True if self.mode == "fix" else not self.records

    @property
    def files(self) -> list[str]:
        return sorted({r["file_path"] for r in self.records})

    def summary(self) -> str:
        if not self.scanned_dirs:
            return "nothing to check"
        if self.mode == "fix":
            return f"{len(self.files)} file(s) fixed" if self.files else "nothing to fix"
        return "no deprecations" if self.ok else f"{len(self.files)} file(s) affected"

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "mode": self.mode,
            "scope": self.scope,
            "scanned_dirs": self.scanned_dirs,
            "files": self.files,
            "deprecations": [{"file_path": r["file_path"], "refactors": r["refactors"]} for r in self.records],
            "logs": [tool_log.to_dict() for tool_log in self.logs],
        }

    def human_lines(self, *, show_passes: bool = False) -> list[tuple[int, str]]:
        # Summary only — the per-refactor descriptions live in the native tool log (below, on
        # failure / --show-logs). Failures-only: a clean check collapses to its one-line verdict;
        # fix mode always reports what it applied.
        label = style.section("deprecations")
        if not self.scanned_dirs:
            return [(INFO, f"{label}  {style.dim('no models to scan — nothing to do.')}")]
        if self.mode != "fix" and self.ok and not show_passes:
            return [(INFO, f"{label}  {style.passed('no dbt deprecations found')}")]
        if self.mode == "fix":
            if self.files:
                lines: list[tuple[int, str]] = [(INFO, f"{label}  {style.passed('applied deprecation fixes')}")]
                lines += [(INFO, style.pass_item(fp)) for fp in self.files]
                return lines
            return [(INFO, f"{label}  {style.passed('nothing to fix')}")]
        if self.records:
            lines = [(ERROR, f"{label}  {style.failed('dbt deprecations detected — see tool logs')}")]
            lines += [(ERROR, style.fail_item(fp)) for fp in self.files]
            lines.append((ERROR, style.dim("   apply with: adaf check deprecations --fix")))
            return lines
        return [(INFO, f"{label}  {style.passed('no dbt deprecations found')}")]
