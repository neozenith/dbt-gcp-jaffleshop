"""``check lint`` and ``check format`` — SQLFluff over the selected models.

SQLFluff splits the concern into two tools, which map onto our two subcommands:

* **lint**   — the FULL ruleset.   check → ``sqlfluff lint``;  ``--fix`` → ``sqlfluff fix``.
* **format** — the opinionated layout+keyword-case subset that ``sqlfluff format`` can
  auto-fix.        check → ``sqlfluff lint --rules <subset>``;  ``--fix`` → ``sqlfluff format``.

In check mode SQLFluff's exit code IS the signal (non-zero = violations). The full violation detail
is captured in the report's ToolLog. The result dataclass lives in ``adaf.reports.sqlfluff``.
"""

# Standard Library
import logging
from pathlib import Path

# Local
from adaf import config
from adaf.reports.sqlfluff import SqlfluffReport
from adaf.utils.toollog import run_tool

log = logging.getLogger(__name__)

__all__ = ["SqlfluffReport", "FORMAT_RULES", "run"]

# The layout + keyword-case rules `sqlfluff format` is able to auto-fix — the formatter's remit.
FORMAT_RULES = "layout,capitalisation.keywords"


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
