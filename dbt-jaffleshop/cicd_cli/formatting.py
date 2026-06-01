"""Shared rendering for check reports.

A "report" is any object exposing:

* ``ok: bool``                                   — did the check pass?
* ``to_dict() -> dict``                          — the machine payload for ``--json``
* ``human_lines(show_passes=False)``             — (logging level, message) pairs for humans
* ``logs: list[ToolLog]`` (optional)             — raw underlying-tool transcripts
* ``scope: str`` (optional)                      — what was selected (printed once as context)

Human output is the concise, emoji-labelled verdict (failures-only by default); the raw tool
transcripts print below it on failure (or with ``--show-logs``). Colour is governed by
``style`` — when it's off, the tool transcripts are stripped of their native ANSI too, so piped
output stays clean. ``--json`` always carries the full result.
"""

# Standard Library
import json
import logging
import sys

# Local
from cicd_cli import style

log = logging.getLogger(__name__)


def emit_tool_logs(report, *, show_logs: bool) -> None:
    """Print a report's underlying-tool transcripts when it failed (or show_logs is set)."""
    logs = getattr(report, "logs", [])
    if not logs or (report.ok and not show_logs):
        return
    log.log(logging.ERROR, style.dim("   ── underlying tool logs ──"))
    for tool_log in logs:
        level = logging.ERROR if tool_log.failed else logging.INFO
        for line in tool_log.human_block():
            if not style.enabled():
                line = style.strip_ansi(line)  # keep piped/redirected output free of escapes
            log.log(level, f"   {line}")


def render(report, *, as_json: bool, show_logs: bool = False, show_passes: bool = False) -> int:
    """Emit a report (JSON to stdout, or scope + human lines + tool logs to stderr); return exit code."""
    if as_json:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
        return 0 if report.ok else 1
    scope = getattr(report, "scope", None)
    if scope:
        log.info(style.dim(f"▸ {scope}"))
    for level, line in report.human_lines(show_passes=show_passes):
        log.log(level, line)
    emit_tool_logs(report, show_logs=show_logs)
    return 0 if report.ok else 1


def render_from_args(report, args) -> int:
    """Render a report pulling the output flags off parsed args — the single call site every
    command handler uses, so none can forget to thread ``--json``/``--show-logs``/``--show-passes``."""
    return render(report, as_json=args.as_json, show_logs=args.show_logs, show_passes=args.show_passes)


def markdown_summary(reports, scope: str) -> str:
    """A GitHub-flavoured Markdown summary table of the checks — the body of a PR comment.

    Detail per check is one line (``report.summary()``); the FULL per-file/per-violation detail
    lives in the run logs, which the workflow links to alongside this table.
    """
    overall = "✅ all checks passed" if all(r.ok for r in reports) else "❌ one or more checks failed"
    lines = [
        f"### cicd_cli checks — {overall}",
        "",
        f"_Scope: {scope}_",
        "",
        "| Check | Status | Detail |",
        "|:--|:--:|:--|",
    ]
    for report in reports:
        emoji = style.EMOJI.get(report.name, "•")
        status = "✅ pass" if report.ok else "❌ fail"
        lines.append(f"| {emoji} `{report.name}` | {status} | {report.summary()} |")
    lines.append("")
    return "\n".join(lines)
