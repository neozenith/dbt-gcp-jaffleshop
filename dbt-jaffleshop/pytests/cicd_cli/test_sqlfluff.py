# Standard Library
from pathlib import Path

# Local
from cicd_cli.commands.sqlfluff import FORMAT_RULES, SqlfluffReport, _command, run
from cicd_cli.toollog import ToolLog


def test_command_mapping_lint_check_and_fix():
    assert _command("lint", "check", ["a.sql"]) == ["sqlfluff", "lint", "a.sql"]
    assert _command("lint", "fix", ["a.sql"]) == ["sqlfluff", "fix", "a.sql"]


def test_command_mapping_format_check_uses_rule_subset():
    cmd = _command("format", "check", ["a.sql"])
    assert cmd == ["sqlfluff", "lint", "--rules", FORMAT_RULES, "a.sql"]


def test_command_mapping_format_fix_invokes_formatter():
    assert _command("format", "fix", ["a.sql"]) == ["sqlfluff", "format", "a.sql"]


def _report(returncode: int, stdout: str = "", stderr: str = "") -> SqlfluffReport:
    tool_log = ToolLog(["sqlfluff", "lint", "a.sql"], returncode, stdout, stderr)
    return SqlfluffReport("lint", "check", "scope", ["a.sql"], returncode, logs=[tool_log])


def test_report_ok_on_zero_returncode():
    report = _report(0, stdout="All Finished!")
    assert report.ok is True
    assert report.to_dict()["check"] == "lint"


def test_report_fails_on_nonzero_and_carries_tool_log():
    report = _report(1, stdout="L:1 | P:1 | LT01 | unexpected indent")
    assert report.ok is False
    payload = report.to_dict()
    assert payload["ok"] is False
    # The raw violation detail must survive into the machine payload for an agent to act on.
    assert payload["logs"][0]["returncode"] == 1
    assert "LT01" in payload["logs"][0]["stdout"]


def test_human_lines_is_a_summary_not_a_raw_dump():
    # The verdict line points at the logs; the raw transcript is rendered separately.
    report = _report(1, stdout="L:1 | P:1 | LT01")
    text = " ".join(line for _level, line in report.human_lines())
    assert "lint violations found" in text
    assert "LT01" not in text  # raw detail lives in logs, not the summary


def test_run_skips_when_no_targets():
    # Empty selection must NOT invoke sqlfluff (which would lint the cwd); it's a clean no-op.
    report = run("lint", [], fix=False, scope="empty scope", cwd=Path("/tmp"))
    assert report.skipped is True
    assert report.ok is True
    assert report.logs == []
    assert "nothing to do" in report.human_lines()[0][1]
