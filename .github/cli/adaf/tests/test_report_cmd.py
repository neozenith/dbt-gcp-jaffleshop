"""Unit tests for the `adaf report` sectioned sticky-comment command (`adaf.commands.report`)."""

# Standard Library
import json
from argparse import Namespace
from pathlib import Path

# Third Party
import pytest

# First Party
from adaf.commands import report as report_cmd
from adaf.dbt import runresults
from adaf.dbt.manifest_view import ManifestView


def _write_findings(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "sqlfluff.json").write_text(
        json.dumps(
            {
                "check": "sqlfluff",
                "exit_code": 1,
                "findings": [{"path": "models/x.sql", "line": 4, "severity": "error", "code": "L010", "message": "m"}],
            }
        ),
        encoding="utf-8",
    )
    (d / "docscov.json").write_text(json.dumps({"check": "docscov", "exit_code": 0, "findings": []}), encoding="utf-8")


def test_findings_section_has_gate_table_and_per_check_details() -> None:
    section = report_cmd.render_findings_section(
        [
            {"check": "sqlfluff", "exit_code": 1, "findings": [{"path": "a.sql", "line": 1, "code": "L1", "message": "x"}]},
            {"check": "docscov", "exit_code": 1, "findings": [{"path": "b.sql", "code": "DOC", "message": "y"}]},
            {"check": "testcov", "exit_code": 0, "findings": []},
        ]
    )
    assert "### Quality gates" in section
    assert "| sqlfluff | ❌ fail | 1 |" in section
    # ONE collapsible per check that HAS findings; the clean check (testcov) gets none.
    assert section.count("<details>") == 2
    assert "<summary><code>sqlfluff</code> — 1 finding(s)</summary>" in section
    assert "<summary><code>docscov</code> — 1 finding(s)</summary>" in section
    assert "<summary><code>testcov</code>" not in section  # the clean check has no collapsible
    assert "### dbt build" not in section  # findings section never mentions the build


def test_findings_section_no_details_when_all_clean() -> None:
    section = report_cmd.render_findings_section([{"check": "docscov", "exit_code": 0, "findings": []}])
    assert "<details>" not in section  # no findings anywhere ⇒ no collapsibles at all


def test_build_section_uses_manifest_names_and_edr_link() -> None:
    rr = runresults.RunResults(
        generated_at="t", elapsed_time=1.0, results=[runresults.Result("test.p.t", "fail", failures=2)]
    )
    view = ManifestView.from_dict({"nodes": {"test.p.t": {"name": "my_test", "original_file_path": "models/s.yml"}}})
    section = report_cmd.render_build_section(
        rr, view.records(), edr_url="http://edr", sdag_url="http://sdag", docs_url="http://docs"
    )
    assert "### dbt build" in section
    assert "| fail | my_test | models/s.yml | 2 failing rows |" in section
    assert "[Download `edr-report` artifact](http://edr)" in section
    assert "[Download `sdag-viewer` artifact](http://sdag)" in section
    assert "[Download `dbt-docs` artifact](http://docs)" in section


def test_build_section_handles_no_run_results() -> None:
    section = report_cmd.render_build_section(None, {}, edr_url=None)
    assert "did not produce results" in section


def test_skeleton_carries_both_sections_with_marker() -> None:
    skel = report_cmd.render_skeleton("demand", "adaf-report")
    assert skel.startswith("<!-- adaf-report -->")
    assert "<!-- adaf:findings -->" in skel and "<!-- /adaf:findings -->" in skel
    assert "<!-- adaf:build -->" in skel and "<!-- /adaf:build -->" in skel
    assert "## 🛡️ ADAF checks — demand" in skel


def test_load_findings_skips_non_findings_json(tmp_path: Path) -> None:
    _write_findings(tmp_path)
    (tmp_path / "junk.json").write_text(json.dumps({"unrelated": True}), encoding="utf-8")
    loaded = report_cmd._load_findings(tmp_path)
    assert sorted(r["check"] for r in loaded) == ["docscov", "sqlfluff"]


def test_resolve_pr_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DBT_PR_NUMBER", raising=False)
    monkeypatch.setenv("GITHUB_REF", "refs/pull/42/merge")
    assert report_cmd._resolve_pr(Namespace(pr=None)) == 42
    monkeypatch.setenv("DBT_PR_NUMBER", "99")
    assert report_cmd._resolve_pr(Namespace(pr=None)) == 99
    assert report_cmd._resolve_pr(Namespace(pr=7)) == 7


def _dry_run_args(tmp_path: Path, section: str) -> Namespace:
    return Namespace(
        findings_dir=tmp_path / "findings",
        run_results=tmp_path / "none.json",
        manifest=tmp_path / "none.json",
        selector="demand",
        edr_url=None,
        sdag_url=None,
        docs_url=None,
        marker="adaf-report",
        section=section,
        dry_run=True,
        repo=None,
        token=None,
        pr=None,
    )


def test_cmd_report_dry_run_all_prints_both_sections(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_findings(tmp_path / "findings")
    assert report_cmd.cmd_report(_dry_run_args(tmp_path, "all")) == 0
    out = capsys.readouterr().out
    assert "ADAF checks — demand" in out
    assert "| sqlfluff | ❌ fail | 1 |" in out  # findings filled
    assert "did not produce results" in out  # build filled (no run_results)


def test_cmd_report_dry_run_findings_only_leaves_build_pending(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_findings(tmp_path / "findings")
    assert report_cmd.cmd_report(_dry_run_args(tmp_path, "findings")) == 0
    out = capsys.readouterr().out
    assert "| sqlfluff | ❌ fail | 1 |" in out  # findings filled
    assert "build pending" in out  # build left as placeholder
