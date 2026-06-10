# Local
from adaf.commands.deprecations import DeprecationsReport, parse_autofix_output

SCOPE = "changed models vs main"

# Two files needing changes, plus the terminal marker and a blank line dbt-autofix emits.
SAMPLE_JSONL = "\n".join(
    [
        '{"mode": "dry_run", "file_path": "models/staging/a.yml", "refactors": [{"deprecation": "D", "log": "l"}]}',
        '{"mode": "dry_run", "file_path": "models/staging/b.yml", "refactors": [{"deprecation": "E", "log": "m"}]}',
        '{"mode": "complete"}',
        "",
    ]
)


def test_parse_keeps_only_records_with_refactors():
    records = parse_autofix_output(SAMPLE_JSONL)
    assert [r["file_path"] for r in records] == ["models/staging/a.yml", "models/staging/b.yml"]


def test_parse_ignores_complete_marker_and_blank_lines():
    assert parse_autofix_output('{"mode": "complete"}\n\n   \n') == []


def test_check_clean_report_is_ok():
    report = DeprecationsReport("check", SCOPE, ["models/staging"], [])
    assert report.ok is True
    assert report.to_dict()["ok"] is True


def test_check_with_records_fails_and_dedupes_files():
    report = DeprecationsReport("check", SCOPE, ["models/staging"], parse_autofix_output(SAMPLE_JSONL))
    assert report.ok is False
    assert report.files == ["models/staging/a.yml", "models/staging/b.yml"]
    payload = report.to_dict()
    assert payload["ok"] is False
    assert payload["mode"] == "check"
    assert len(payload["deprecations"]) == 2


def test_fix_mode_is_ok_even_with_records():
    # In fix mode the changes were applied (errors raise), so a populated record list is success.
    report = DeprecationsReport("fix", SCOPE, ["models/staging"], parse_autofix_output(SAMPLE_JSONL))
    assert report.ok is True
    assert report.files == ["models/staging/a.yml", "models/staging/b.yml"]
    # human output frames it as "applied", not a violation.
    text = " ".join(line for _level, line in report.human_lines())
    assert "applied" in text


def test_no_scanned_dirs_reports_nothing_to_do():
    report = DeprecationsReport("check", SCOPE, [], [])
    assert "nothing to do" in report.human_lines()[0][1]
