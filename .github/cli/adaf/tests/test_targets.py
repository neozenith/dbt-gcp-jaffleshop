"""Tests for ``adaf list`` rendering (``commands.targets.list_targets``) + the ``--commands`` argv
builders on the check gates. All pure / binary-free, so they belong in ``make ci``.
"""

# Standard Library
from pathlib import Path

# Third Party
import pytest

# Local
from adaf.commands.deprecations import argv_for as dep_argv
from adaf.commands.sqlfluff import argv_for as fluff_argv
from adaf.commands.targets import list_targets


# ─── list_targets ──────────────────────────────────────────────────────────────


def test_list_targets_paths_on_stdout_headline_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    rc = list_targets("modified", ["models/a.sql", "models/b.sql"], color=False)
    captured = capsys.readouterr()
    assert rc == 0
    out_lines = captured.out.strip().split("\n")
    assert out_lines == ["models/a.sql", "models/b.sql"]  # no hops → flat, pipeable paths, no group titles
    assert "modified" in captured.err  # scope headline on stderr
    assert "2 model(s)" in captured.err


def test_list_targets_groups_upstream_downstream_with_titles(capsys: pytest.CaptureFixture[str]) -> None:
    rc = list_targets(
        "all + 1 hop",
        ["models/a.sql"],
        color=False,
        upstream=[("source.p.raw_orders", "source")],
        downstream=[("models/consumer.sql", None)],
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "== selector models (1) ==" in captured.err
    assert "== upstream (1) ==" in captured.err
    assert "== downstream (1) ==" in captured.err
    assert "3 node(s)" in captured.err
    out = captured.out
    assert "models/a.sql" in out
    assert "source.p.raw_orders  [source]" in out
    assert "models/consumer.sql" in out


def test_list_targets_bare_drops_group_titles(capsys: pytest.CaptureFixture[str]) -> None:
    rc = list_targets(
        "all + 1 hop",
        ["models/a.sql"],
        color=False,
        bare=True,
        upstream=[("source.p.raw_orders", "source")],
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "==" not in captured.err  # bare → no group titles
    out_lines = captured.out.strip().split("\n")
    assert out_lines == ["models/a.sql", "source.p.raw_orders  [source]"]  # flat


def test_list_targets_sections_distinguished_by_hue(capsys: pytest.CaptureFixture[str]) -> None:
    # Sections are hue-coded: selector neutral grey (light grey if git-modified, dark grey if not),
    # upstream amber (yellow), downstream green.
    list_targets(
        "all + 1 hop",
        ["models/changed.sql", "models/unchanged.sql"],
        color=True,
        changed={"models/changed.sql"},
        upstream=[("models/up.sql", None)],
        downstream=[("models/down.sql", None)],
    )
    out = capsys.readouterr().out
    line = lambda frag: next(ln for ln in out.splitlines() if frag in ln)  # noqa: E731
    assert "\x1b[37m" in line("changed.sql")  # selector modified → light grey
    assert "\x1b[90m" in line("unchanged.sql")  # selector unmodified → dark grey
    assert "\x1b[33m" in line("up.sql")  # upstream → amber (yellow)
    assert "\x1b[32m" in line("down.sql")  # downstream → green


def test_list_targets_no_color_has_no_ansi(capsys: pytest.CaptureFixture[str]) -> None:
    list_targets("all", ["models/a.sql"], color=False)
    captured = capsys.readouterr()
    assert "\x1b[" not in captured.out
    assert "\x1b[" not in captured.err


def test_list_targets_empty(capsys: pytest.CaptureFixture[str]) -> None:
    rc = list_targets("modified", [], color=False)
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() == ""
    assert "0 model(s)" in captured.err


# ─── --commands argv builders (single source of truth for running AND printing) ─


def test_deprecation_argv_detection_is_dry_run_json() -> None:
    assert dep_argv(Path("models/demand"), fix=False) == [
        "dbt-autofix",
        "deprecations",
        "-s",
        "models/demand",
        "-d",
        "--json",
    ]


def test_deprecation_argv_fix_drops_dry_run_and_json() -> None:
    assert dep_argv(Path("models/demand"), fix=True) == ["dbt-autofix", "deprecations", "-s", "models/demand"]


@pytest.mark.parametrize(
    "name,fix,expected",
    [
        ("lint", False, ["sqlfluff", "lint", "models/a.sql"]),
        ("lint", True, ["sqlfluff", "fix", "models/a.sql"]),
        ("format", False, ["sqlfluff", "lint", "--rules", "layout,capitalisation.keywords", "models/a.sql"]),
        ("format", True, ["sqlfluff", "format", "models/a.sql"]),
    ],
)
def test_sqlfluff_argv(name: str, fix: bool, expected: list[str]) -> None:
    assert fluff_argv(name, [Path("models/a.sql")], fix=fix) == expected
