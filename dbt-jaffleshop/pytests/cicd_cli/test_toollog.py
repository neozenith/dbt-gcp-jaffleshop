# Standard Library
from pathlib import Path

# Local
from cicd_cli.toollog import ToolLog, run_tool


def test_run_tool_captures_success(tmp_path: Path):
    # `git --version` is a real, dependency-free command available in CI and locally.
    tool_log = run_tool(["git", "--version"], cwd=tmp_path)
    assert tool_log.returncode == 0
    assert tool_log.failed is False
    assert "git version" in tool_log.stdout


def test_run_tool_captures_failure_and_stderr(tmp_path: Path):
    tool_log = run_tool(["git", "definitely-not-a-real-subcommand"], cwd=tmp_path)
    assert tool_log.failed is True
    assert tool_log.returncode != 0
    # git writes the "not a git command" message to stderr — exactly the signal we must keep.
    assert tool_log.stderr.strip() != ""


def test_to_dict_shape():
    tool_log = ToolLog(["sqlfluff", "lint", "a.sql"], 1, "L:1 | P:1 | LT01", "warn")
    payload = tool_log.to_dict()
    assert payload == {
        "command": "sqlfluff lint a.sql",
        "returncode": 1,
        "stdout": "L:1 | P:1 | LT01",
        "stderr": "warn",
    }


def test_human_block_includes_command_stdout_and_labelled_stderr():
    tool_log = ToolLog(["dbt", "parse"], 2, "compiling\nerror", "boom")
    block = tool_log.human_block()
    assert block[0] == "$ dbt parse  (exit 2)"
    assert "  compiling" in block
    assert "  error" in block
    assert "  [stderr] boom" in block


def test_tty_mode_captures_output_and_merges_streams(tmp_path: Path):
    # Under a pty there's a single stream, so output lands in stdout and stderr is empty.
    tool_log = run_tool(["git", "--version"], cwd=tmp_path, tty=True)
    assert tool_log.returncode == 0
    assert "git version" in tool_log.stdout
    assert tool_log.stderr == ""


def test_tty_mode_merges_error_text_into_stdout(tmp_path: Path):
    tool_log = run_tool(["git", "not-a-real-subcommand"], cwd=tmp_path, tty=True)
    assert tool_log.failed
    assert tool_log.stderr == ""  # merged by the pty
    assert "not-a-real-subcommand" in tool_log.stdout
