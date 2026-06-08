"""``check lint`` and ``check format`` — SQLFluff over the selected models.

SQLFluff splits the concern into two tools, which map onto our two subcommands:

* **lint**   — the FULL ruleset.   check → ``sqlfluff lint``;  ``--fix`` → ``sqlfluff fix``.
* **format** — the opinionated layout+keyword-case subset that ``sqlfluff format`` can
  auto-fix.        check → ``sqlfluff lint --rules <subset>``;  ``--fix`` → ``sqlfluff format``.

In check mode SQLFluff's exit code IS the signal (non-zero = violations). The full
violation detail — and, after ``--fix``, the "lint for unfixable violations" section listing
what must be fixed by hand — is captured in the report's ToolLog and printed on failure.
"""

# Standard Library
import logging
from dataclasses import dataclass, field
from pathlib import Path

# Local
from adaf import config, style
from adaf.toollog import ToolLog, run_tool

log = logging.getLogger(__name__)

INFO = logging.INFO
ERROR = logging.ERROR

# The layout + keyword-case rules `sqlfluff format` is able to auto-fix — the formatter's
# remit, kept identical to the Makefile's old `format-check` target.
FORMAT_RULES = "layout,capitalisation.keywords"

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


def _command(name: str, mode: str, targets: list[str]) -> list[str]:
    if name == "lint":
        return ["sqlfluff", "fix", *targets] if mode == "fix" else ["sqlfluff", "lint", *targets]
    # format
    if mode == "fix":
        return ["sqlfluff", "format", *targets]
    return ["sqlfluff", "lint", "--rules", FORMAT_RULES, *targets]


def run(name: str, files: list[Path], *, fix: bool, scope: str, cwd: Path | None = None) -> SqlfluffReport:
    cwd = cwd or config.PROJECT_ROOT
    mode = "fix" if fix else "check"
    targets = [str(f) for f in files]
    if not targets:
        return SqlfluffReport(name, mode, scope, [], 0, skipped=True)
    # tty=True so SQLFluff emits its native, COLOURED output into the log (it strips ANSI when
    # piped). Its exit code is still the pass/fail signal.
    tool_log = run_tool(_command(name, mode, targets), cwd=cwd, tty=True)
    return SqlfluffReport(name, mode, scope, targets, tool_log.returncode, logs=[tool_log])
