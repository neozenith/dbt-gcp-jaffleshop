"""Result dataclass for ``check lint`` / ``check format`` (SQLFluff)."""

import logging
from dataclasses import dataclass, field

from adaf.utils import style
from adaf.utils.toollog import ToolLog

INFO = logging.INFO
ERROR = logging.ERROR

_SUMMARY = {
    ("lint", "check"): ("lint clean", "lint violations found"),
    ("lint", "fix"): ("lint auto-fixes applied", "unfixable lint violations remain"),
    ("format", "check"): ("formatting clean", "formatting drift found (run with --fix)"),
    ("format", "fix"): ("formatting applied", "formatter errored"),
}


@dataclass
class SqlfluffReport:
    name: str  # "lint" or "format"
    mode: str  # "check" or "fix"
    scope: str
    targets: list[str]
    returncode: int
    logs: list[ToolLog] = field(default_factory=list)
    skipped: bool = False

    @property
    def ok(self) -> bool:
        return self.skipped or self.returncode == 0

    def summary(self) -> str:
        if self.skipped:
            return "no models"
        ok_msg, fail_msg = _SUMMARY[(self.name, self.mode)]
        return ok_msg if self.ok else fail_msg

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "mode": self.mode,
            "scope": self.scope,
            "targets": self.targets,
            "returncode": self.returncode,
            "skipped": self.skipped,
            "logs": [tool_log.to_dict() for tool_log in self.logs],
        }

    def human_lines(self, *, show_passes: bool = False) -> list[tuple[int, str]]:
        label = style.section(self.name)
        verb = "fix" if self.mode == "fix" else "check"
        if self.skipped:
            return [(INFO, f"{label}  {style.dim(f'no models to {verb} — nothing to do.')}")]
        ok_msg, fail_msg = _SUMMARY[(self.name, self.mode)]
        suffix = style.dim(f" ({self.mode}, {len(self.targets)} model(s))")
        if self.ok:
            return [(INFO, f"{label}  {style.passed(ok_msg)}{suffix}")]
        return [(ERROR, f"{label}  {style.failed(fail_msg + ' — see tool logs')}{suffix}")]
