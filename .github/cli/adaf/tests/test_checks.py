"""Tests for ``adaf.commands.checks``.

The two gates shell out to external binaries (dbt-autofix / sqlfluff), which the project's
test rules forbid invoking (and forbid mocking). So the binary-driven entry points are not
exercised here; instead the pure JSON-record→:class:`~adaf.report.Finding` parsers
(:func:`_deprecation_findings`, :func:`_sqlfluff_findings`, :func:`_extract_line`) are unit
-tested against canned payloads, and the binary-free :func:`list_targets` is tested via capsys.
"""

# Standard Library
from pathlib import Path
from typing import Any

# Third Party
import pytest

# Local
from adaf.commands.checks import (
    _deprecation_argv,
    _deprecation_findings,
    _extract_line,
    _sqlfluff_argv,
    _sqlfluff_findings,
    check_deprecations,
    check_sqlfluff,
    list_targets,
)

# --------------------------------------------------------------------------------------
# list_targets
# --------------------------------------------------------------------------------------


def test_list_targets_paths_on_stdout_headline_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    rc = list_targets("modified", ["models/a.sql", "models/b.sql"], color=False)
    captured = capsys.readouterr()
    assert rc == 0
    out_lines = captured.out.strip().split("\n")
    assert out_lines == ["models/a.sql", "models/b.sql"]  # no hops → flat, pipeable paths, no group titles
    assert "modified" in captured.err  # scope headline on stderr
    assert "2 model(s)" in captured.err


def test_list_targets_groups_upstream_downstream_with_titles(capsys: pytest.CaptureFixture[str]) -> None:
    # With hop nodes, each direction gets its own == group == title (on stderr); non-model nodes carry
    # a [type] tag and render in darker grey. This is the grouped (non-bare) default.
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


def test_list_targets_defer_splits_each_group_into_built_and_deferred(capsys: pytest.CaptureFixture[str]) -> None:
    # --defer passes a `built` set (the state:modified+ models); each group is then split into a
    # built then a deferred sub-section, each under a `-- … --` sub-header (on stderr).
    rc = list_targets(
        "modified",
        ["models/a.sql", "models/b.sql", "models/c.sql"],
        color=False,
        built={"models/a.sql", "models/c.sql"},
    )
    captured = capsys.readouterr()
    assert rc == 0
    # Sub-headers count each partition; built precedes deferred.
    assert "-- built (2) --" in captured.err
    assert "-- deferred (1) --" in captured.err
    # Defer forces the grouped layout even with no hop nodes, so the group title appears too.
    assert "== selector models (3) ==" in captured.err
    # STDOUT stays a clean path stream, ordered built (a, c) then deferred (b).
    out_lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert out_lines == ["models/a.sql", "models/c.sql", "models/b.sql"]


def test_list_targets_defer_subgroups_apply_within_hop_groups(capsys: pytest.CaptureFixture[str]) -> None:
    rc = list_targets(
        "all + hops",
        ["models/a.sql"],
        color=False,
        upstream=[("models/up_built.sql", None), ("models/up_def.sql", None)],
        downstream=[("models/down.sql", None)],
        built={"models/a.sql", "models/up_built.sql"},
    )
    err = capsys.readouterr().err
    assert rc == 0
    # Each existing group still gets its == title ==, now with built/deferred sub-headers inside.
    assert "== selector models (1) ==" in err
    assert "== upstream (2) ==" in err
    assert "== downstream (1) ==" in err
    # upstream has one built + one deferred; downstream is purely deferred (down.sql not in built).
    assert "-- built (1) --" in err  # the built upstream node
    assert "-- deferred (1) --" in err


def test_list_targets_bare_ignores_defer_subgroups(capsys: pytest.CaptureFixture[str]) -> None:
    rc = list_targets("modified", ["models/a.sql", "models/b.sql"], color=False, bare=True, built={"models/a.sql"})
    captured = capsys.readouterr()
    assert rc == 0
    assert "-- built" not in captured.err  # bare stays a flat, sub-header-free pipeable list
    assert captured.out.strip().split("\n") == ["models/a.sql", "models/b.sql"]


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


def test_list_targets_color_emits_ansi(capsys: pytest.CaptureFixture[str]) -> None:
    list_targets("all", ["models/a.sql"], color=True)
    captured = capsys.readouterr()
    assert "\x1b[" in captured.out  # path colourised
    assert "models/a.sql" in captured.out


def test_list_targets_empty(capsys: pytest.CaptureFixture[str]) -> None:
    rc = list_targets("modified", [], color=False)
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() == ""
    assert "0 model(s)" in captured.err


# --------------------------------------------------------------------------------------
# _extract_line
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ref,expected",
    [
        ({"log": "x"}, None),  # current dbt-autofix shape: no location
        ({"line": 12}, 12),
        ({"lineno": 7}, 7),
        ({"line_no": 3}, 3),
        ({"start_line_no": 9}, 9),
        ({"line_number": 5}, 5),
        ({"location": {"line": 21}}, 21),
        ({"range": {"start_line_no": 4}}, 4),
        ({"range": {"start": 6}}, 6),
        ({"line": "nope"}, None),  # non-int ignored
        ({"line": True}, None),  # bool is not a line number
    ],
)
def test_extract_line(ref: dict[str, Any], expected: int | None) -> None:
    assert _extract_line(ref) == expected


# --------------------------------------------------------------------------------------
# _deprecation_findings
# --------------------------------------------------------------------------------------


def test_deprecation_findings_basic() -> None:
    records = [
        {
            "mode": "dry_run",
            "file_path": "models/x.yml",
            "refactors": [
                {"deprecation": "custom-key", "log": "moved foo under config"},
                {"deprecation": "tests-to-data-tests", "log": "renamed tests"},
            ],
        }
    ]
    findings = _deprecation_findings(records)
    assert len(findings) == 2
    first = findings[0]
    assert first.path == "models/x.yml"
    assert first.severity == "warn"
    assert first.code == "custom-key"
    assert first.message == "moved foo under config"
    assert first.line is None  # no location in dbt-autofix output today


def test_deprecation_findings_dedup_first_wins() -> None:
    records = [
        {"file_path": "dbt_project.yml", "refactors": [{"deprecation": "a", "log": "first"}]},
        {"file_path": "dbt_project.yml", "refactors": [{"deprecation": "a", "log": "second"}]},
    ]
    findings = _deprecation_findings(records)
    assert len(findings) == 1
    assert findings[0].message == "first"


def test_deprecation_findings_skips_empty_refactors_and_missing_path() -> None:
    records = [
        {"file_path": "models/clean.sql", "refactors": []},
        {"file_path": "models/clean.sql"},  # no refactors key
        {"refactors": [{"deprecation": "a", "log": "orphan"}]},  # no file_path
    ]
    assert _deprecation_findings(records) == []


def test_deprecation_findings_code_falls_back_to_name() -> None:
    records = [{"file_path": "m.yml", "refactors": [{"name": "rule-x", "log": "detail"}]}]
    findings = _deprecation_findings(records)
    assert findings[0].code == "rule-x"


def test_deprecation_findings_extracts_future_line() -> None:
    records = [{"file_path": "m.yml", "refactors": [{"deprecation": "a", "log": "d", "line": 42}]}]
    findings = _deprecation_findings(records)
    assert findings[0].line == 42


# --------------------------------------------------------------------------------------
# _sqlfluff_findings
# --------------------------------------------------------------------------------------


def test_sqlfluff_findings_v3_shape() -> None:
    payload = [
        {
            "filepath": "models/a.sql",
            "violations": [
                {
                    "start_line_no": 1,
                    "start_line_pos": 1,
                    "code": "CP01",
                    "description": "Keywords must be upper case.",
                    "name": "capitalisation.keywords",
                },
                {
                    "start_line_no": 1,
                    "start_line_pos": 8,
                    "code": "CV03",
                    "description": "Trailing comma in select statement required",
                },
            ],
        }
    ]
    findings = _sqlfluff_findings(payload)
    assert len(findings) == 2
    f0 = findings[0]
    assert f0.path == "models/a.sql"
    assert f0.line == 1
    assert f0.col == 1
    assert f0.code == "CP01"
    assert f0.message == "Keywords must be upper case."
    assert f0.severity == "error"
    assert findings[1].col == 8


def test_sqlfluff_findings_v2_shape_fallback() -> None:
    payload = [
        {
            "filepath": "models/b.sql",
            "violations": [{"line_no": 4, "line_pos": 2, "code": "L010", "description": "old shape"}],
        }
    ]
    findings = _sqlfluff_findings(payload)
    assert findings[0].line == 4
    assert findings[0].col == 2
    assert findings[0].code == "L010"


def test_sqlfluff_findings_empty_and_clean_files() -> None:
    assert _sqlfluff_findings([]) == []
    assert _sqlfluff_findings([{"filepath": "clean.sql", "violations": []}]) == []


def test_sqlfluff_findings_multiple_files() -> None:
    def _file(name: str, code: str) -> dict[str, Any]:
        violation = {"start_line_no": 1, "start_line_pos": 1, "code": code, "description": ""}
        return {"filepath": name, "violations": [violation]}

    payload = [_file("a.sql", "X"), _file("b.sql", "Y")]
    findings = _sqlfluff_findings(payload)
    assert [f.path for f in findings] == ["a.sql", "b.sql"]


# --------------------------------------------------------------------------------------
# argv builders (single source of truth for running AND printing the command)
# --------------------------------------------------------------------------------------


def test_deprecation_argv_detection_is_dry_run_json() -> None:
    assert _deprecation_argv(Path("models/demand"), fix=False) == [
        "dbt-autofix",
        "deprecations",
        "-s",
        "models/demand",
        "-d",
        "--json",
    ]


def test_deprecation_argv_fix_drops_dry_run_and_json() -> None:
    assert _deprecation_argv(Path("models/demand"), fix=True) == [
        "dbt-autofix",
        "deprecations",
        "-s",
        "models/demand",
    ]


@pytest.mark.parametrize(
    "fix,fmt,expected",
    [
        (False, None, ["sqlfluff", "lint", "--format", "json", "a.sql"]),
        (False, "github-annotation-native", ["sqlfluff", "lint", "--format", "github-annotation-native", "a.sql"]),
        (True, None, ["sqlfluff", "fix", "--force", "a.sql"]),
        (True, "github-annotation-native", ["sqlfluff", "fix", "--force", "a.sql"]),  # --fix wins over --format
    ],
)
def test_sqlfluff_argv(fix: bool, fmt: str | None, expected: list[str]) -> None:
    assert _sqlfluff_argv(["a.sql"], fix=fix, fmt=fmt) == expected


# --------------------------------------------------------------------------------------
# --commands: print the exact subprocess command(s) instead of running them
# --------------------------------------------------------------------------------------


def _stdout_lines(captured: pytest.CaptureFixture[str]) -> list[str]:
    return [ln for ln in captured.readouterr().out.splitlines() if ln.strip()]


def test_deprecations_commands_prints_one_runnable_line_per_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = [Path("models/demand/a.sql"), Path("models/demand/b.sql"), Path("models/other/c.sql")]
    rc = check_deprecations(files, commands=True, cwd=tmp_path)
    assert rc == 0  # nothing executed
    # One command per unique folder, sorted; the dry-run JSON detection form.
    assert _stdout_lines(capsys) == [
        "dbt-autofix deprecations -s models/demand -d --json",
        "dbt-autofix deprecations -s models/other -d --json",
    ]


def test_deprecations_commands_fix_prints_apply_form(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = check_deprecations([Path("models/demand/a.sql")], fix=True, commands=True, cwd=tmp_path)
    assert rc == 0
    assert _stdout_lines(capsys) == ["dbt-autofix deprecations -s models/demand"]


def test_sqlfluff_commands_prints_lint_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = check_sqlfluff([Path("models/demand/a.sql")], commands=True, cwd=tmp_path)
    assert rc == 0
    assert _stdout_lines(capsys) == ["sqlfluff lint --format json models/demand/a.sql"]


def test_sqlfluff_commands_fix_prints_fix_force(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = check_sqlfluff([Path("models/demand/a.sql")], fix=True, commands=True, cwd=tmp_path)
    assert rc == 0
    assert _stdout_lines(capsys) == ["sqlfluff fix --force models/demand/a.sql"]


def test_commands_headline_on_stderr_not_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    check_sqlfluff([Path("models/demand/a.sql")], commands=True, cwd=tmp_path)
    captured = capsys.readouterr()
    assert "command(s)" in captured.err  # the human headline
    assert "command(s)" not in captured.out  # stdout stays a clean, pipeable command stream
    assert captured.out.strip() == "sqlfluff lint --format json models/demand/a.sql"


def test_commands_empty_scope_returns_zero_with_no_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert check_deprecations([], commands=True, cwd=tmp_path) == 0
    assert check_sqlfluff([], commands=True, cwd=tmp_path) == 0
    captured = capsys.readouterr()
    assert "no files in scope" in captured.err
    assert captured.out.strip() == ""
