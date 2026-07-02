"""Unit tests for the JSON findings emission (`--json-out` / `-q`) substrate in `adaf.report`."""

# Standard Library
import json
from pathlib import Path

# Third Party
import pytest

# First Party
from adaf import report


def _findings() -> list[report.Finding]:
    return [
        report.Finding(path="models/a.sql", line=3, col=1, severity="error", code="L010", message="upper case"),
        report.Finding(path="models/b.sql", severity="warn", code="DOCSCOV", message="no description"),
    ]


def test_finding_to_dict_drops_path_color() -> None:
    f = report.Finding(path="x.sql", line=1, severity="error", code="C", message="m", path_color="grey")
    assert f.to_dict() == {"path": "x.sql", "line": 1, "col": None, "severity": "error", "code": "C", "message": "m"}


def test_write_findings_json_schema(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "sqlfluff.json"
    report.write_findings_json(out, "sqlfluff", 1, _findings())
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["check"] == "sqlfluff"
    assert payload["exit_code"] == 1
    assert [f["code"] for f in payload["findings"]] == ["L010", "DOCSCOV"]


def test_emit_findings_json_only_when_quiet(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "f.json"
    rc = report.emit_findings(
        "sqlfluff", _findings(), 1, color=False, json_out=out, quiet=True, headline="head", severity="error"
    )
    assert rc == 1
    assert out.exists()  # JSON written
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""  # quiet ⇒ no text


def test_emit_findings_both_writes_json_and_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "f.json"
    report.emit_findings("sqlfluff", _findings(), 1, color=False, json_out=out, quiet=False, headline="head")
    captured = capsys.readouterr()
    assert out.exists()  # JSON written
    assert "head" in captured.err  # headline on stderr
    assert "models/a.sql:3:1" in captured.out  # findings on stdout


def test_emit_findings_logs_only_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = report.emit_findings("docscov", [], 0, color=False, headline="ok", severity="ok")
    assert rc == 0
    assert not list(tmp_path.iterdir())  # no JSON file created
    assert "ok" in capsys.readouterr().err
