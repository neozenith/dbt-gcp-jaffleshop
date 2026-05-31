"""End-to-end smoke tests: invoke the real `python -m cicd_cli` process.

These exercise the argparse wiring and the `-m` invocation contract (cwd-on-path
discovery). cwd is anchored to the package's parent (the dbt project root) so the
test is independent of where pytest itself was launched.
"""

# Standard Library
import subprocess
import sys
from pathlib import Path

# Local
import cicd_cli

PROJECT_ROOT = Path(cicd_cli.__file__).resolve().parent.parent


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "cicd_cli", *args],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )


def test_top_level_help_exits_zero():
    proc = _run("--help")
    assert proc.returncode == 0
    assert "check" in proc.stdout


def test_check_help_lists_all_leaves():
    proc = _run("check", "--help")
    assert proc.returncode == 0
    for leaf in ("deprecations", "docs", "tests", "all"):
        assert leaf in proc.stdout


def test_no_command_prints_help_and_exits_zero():
    # No subcommand → the _help default handler fires (argparse required=False pattern).
    proc = _run()
    assert proc.returncode == 0
    assert "usage:" in proc.stdout


def test_unknown_flag_is_a_usage_error():
    proc = _run("check", "docs", "--definitely-not-a-flag")
    assert proc.returncode == 2  # argparse usage error
