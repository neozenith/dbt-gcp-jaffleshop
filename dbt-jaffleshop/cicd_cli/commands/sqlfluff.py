"""``check lint`` and ``check format`` — SQLFluff over the selected models.

SQLFluff splits the concern into two tools, which map onto our two subcommands:

* **lint**   — the FULL ruleset.   check → ``sqlfluff lint``;  ``--fix`` → ``sqlfluff fix``.
* **format** — the opinionated layout+keyword-case subset that ``sqlfluff format`` can
  auto-fix.        check → ``sqlfluff lint --rules <subset>``;  ``--fix`` → ``sqlfluff format``.

In check mode SQLFluff's exit code IS the signal (non-zero = violations), so we surface
it directly. ``stdin`` is closed to guarantee non-interactive behaviour in CI.
"""

# Standard Library
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Local
from cicd_cli import config

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
    output: str
    skipped: bool = False

    @property
    def ok(self) -> bool:
        return self.skipped or self.returncode == 0

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "mode": self.mode,
            "scope": self.scope,
            "targets": self.targets,
            "returncode": self.returncode,
            "skipped": self.skipped,
            "output": self.output,
        }

    def human_lines(self) -> list[tuple[int, str]]:
        verb = "fix" if self.mode == "fix" else "check"
        if self.skipped:
            return [(INFO, f"{self.name}: no models to {verb} ({self.scope}) — nothing to do.")]
        lines: list[tuple[int, str]] = [
            (INFO, f"{self.name} ({self.mode}) on {len(self.targets)} model(s) — {self.scope}:")
        ]
        level = INFO if self.ok else ERROR
        lines += [(level, f"  {line}") for line in self.output.splitlines() if line.strip()]
        ok_msg, fail_msg = _SUMMARY[(self.name, self.mode)]
        lines.append((INFO if self.ok else ERROR, f"{'✓' if self.ok else '✗'} {ok_msg if self.ok else fail_msg}"))
        return lines


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
        return SqlfluffReport(name, mode, scope, [], 0, "", skipped=True)
    proc = subprocess.run(
        _command(name, mode, targets),
        cwd=cwd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    return SqlfluffReport(name, mode, scope, targets, proc.returncode, proc.stdout.strip())
