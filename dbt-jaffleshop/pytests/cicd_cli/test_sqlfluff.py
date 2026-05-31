# Standard Library
from pathlib import Path

# Local
from cicd_cli.commands.sqlfluff import FORMAT_RULES, SqlfluffReport, _command, run


def test_command_mapping_lint_check_and_fix():
    assert _command("lint", "check", ["a.sql"]) == ["sqlfluff", "lint", "a.sql"]
    assert _command("lint", "fix", ["a.sql"]) == ["sqlfluff", "fix", "a.sql"]


def test_command_mapping_format_check_uses_rule_subset():
    cmd = _command("format", "check", ["a.sql"])
    assert cmd == ["sqlfluff", "lint", "--rules", FORMAT_RULES, "a.sql"]


def test_command_mapping_format_fix_invokes_formatter():
    assert _command("format", "fix", ["a.sql"]) == ["sqlfluff", "format", "a.sql"]


def test_report_ok_on_zero_returncode():
    report = SqlfluffReport("lint", "check", "scope", ["a.sql"], 0, "All Finished!")
    assert report.ok is True
    assert report.to_dict()["check"] == "lint"


def test_report_fails_on_nonzero_returncode():
    report = SqlfluffReport("lint", "check", "scope", ["a.sql"], 1, "L:1 | P:1 | LT01")
    assert report.ok is False
    assert report.to_dict()["ok"] is False


def test_run_skips_when_no_targets():
    # Empty selection must NOT invoke sqlfluff (which would lint the cwd); it's a clean no-op.
    report = run("lint", [], fix=False, scope="empty scope", cwd=Path("/tmp"))
    assert report.skipped is True
    assert report.ok is True
    assert "nothing to do" in report.human_lines()[0][1]
