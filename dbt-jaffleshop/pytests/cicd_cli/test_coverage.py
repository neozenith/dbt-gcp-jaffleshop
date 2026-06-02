# Standard Library
from pathlib import Path

# Local
from cicd_cli.catalog import Catalog
from cicd_cli.commands.coverage import ColumnsReport, evaluate_columns, evaluate_docs, evaluate_tests
from cicd_cli.manifest import Manifest

SCOPE = "changed models vs main"

# --------------------------------------------------------- docs (model descriptions)


def test_docs_passes_model_with_description(manifest: Manifest):
    report = evaluate_docs(manifest, [Path("models/marts/documented.sql")], scope=SCOPE)
    assert report.rows[0].has_description is True
    assert report.ok is True


def test_docs_is_model_level_only_ignores_undocumented_columns(manifest: Manifest):
    # partial_cols has a model description but an undocumented column — that's the `doc-columns`
    # check's concern now, so docs passes it.
    report = evaluate_docs(manifest, [Path("models/staging/partial_cols.sql")], scope=SCOPE)
    assert report.rows[0].has_description is True
    assert report.ok is True


def test_docs_flags_missing_model_description(manifest: Manifest):
    report = evaluate_docs(manifest, [Path("models/marts/no_desc.sql")], scope=SCOPE)
    assert report.rows[0].has_description is False
    assert report.ok is False


def test_docs_model_absent_from_manifest_fails(manifest: Manifest):
    report = evaluate_docs(manifest, [Path("models/marts/ghost.sql")], scope=SCOPE)
    assert report.rows[0].in_manifest is False
    assert report.ok is False


def test_docs_empty_changeset_is_ok(manifest: Manifest):
    report = evaluate_docs(manifest, [], scope=SCOPE)
    assert report.rows == []
    assert report.ok is True


# ----------------------------------------------------- columns (column descriptions)


def test_columns_uses_resolved_columns_with_ratio(manifest: Manifest, catalog: Catalog):
    # partial_cols: catalog has id, blank, extra; only id is described → 1/3, missing blank+extra
    # (note `extra` was never declared in YAML — the manifest-only check could not have seen it).
    report = evaluate_columns(manifest, catalog, [Path("models/staging/partial_cols.sql")], scope=SCOPE)
    row = report.rows[0]
    assert (row.documented, row.total) == (1, 3)
    assert row.ratio == "1/3"
    assert row.undocumented_columns == ["blank", "extra"]
    assert row.ok is False
    text = _text(report)
    assert "1/3 columns documented" in text
    assert "blank" in text and "extra" in text


def test_columns_resolved_total_exceeds_declared(manifest: Manifest, catalog: Catalog):
    # no_desc declares NO columns, but the warehouse (catalog) has 2 → 0/2 (the manifest-only
    # check would have called this vacuously ok — this is the whole point of catalog.json).
    report = evaluate_columns(manifest, catalog, [Path("models/marts/no_desc.sql")], scope=SCOPE)
    assert report.rows[0].ratio == "0/2"
    assert report.ok is False


def test_columns_passes_fully_documented_model(manifest: Manifest, catalog: Catalog):
    report = evaluate_columns(manifest, catalog, [Path("models/marts/documented.sql")], scope=SCOPE)
    assert report.rows[0].ratio == "1/1"
    assert report.ok is True


def test_columns_model_not_in_catalog_fails(manifest: Manifest):
    report = evaluate_columns(manifest, Catalog.from_dict({}), [Path("models/marts/documented.sql")], scope=SCOPE)
    assert report.rows[0].in_catalog is False
    assert report.ok is False
    assert "not in catalog" in _text(report)


def test_columns_model_absent_from_manifest_fails(manifest: Manifest, catalog: Catalog):
    report = evaluate_columns(manifest, catalog, [Path("models/marts/ghost.sql")], scope=SCOPE)
    assert report.rows[0].in_manifest is False
    assert report.ok is False


def test_columns_to_dict_shape(manifest: Manifest, catalog: Catalog):
    payload = evaluate_columns(manifest, catalog, [Path("models/staging/partial_cols.sql")], scope=SCOPE).to_dict()
    assert payload["check"] == "doc-columns"
    assert payload["ok"] is False
    assert payload["error"] is None
    result = payload["results"][0]
    assert result["undocumented_columns"] == ["blank", "extra"]
    assert (result["documented"], result["total"]) == (1, 3)


def test_columns_report_error_state_when_catalog_missing():
    report = ColumnsReport(SCOPE, [], error="dbt catalog not found at 'target/catalog.json'.")
    assert report.ok is False
    assert "not found" in _text(report)
    assert report.to_dict()["error"]


# -------------------------------------------------------------------------- tests


def test_tests_flags_untested_model(manifest: Manifest):
    report = evaluate_tests(manifest, [Path("models/staging/partial_cols.sql")], scope=SCOPE)
    assert report.rows[0].test_count == 0
    assert report.ok is False


def test_tests_counts_and_passes_tested_model(manifest: Manifest):
    report = evaluate_tests(manifest, [Path("models/marts/documented.sql")], scope=SCOPE)
    assert report.rows[0].test_count == 2
    assert report.ok is True


def test_tests_model_absent_from_manifest_fails(manifest: Manifest):
    report = evaluate_tests(manifest, [Path("models/x.sql")], scope=SCOPE)
    assert report.rows[0].in_manifest is False
    assert report.ok is False


def test_to_dict_shape_is_machine_friendly(manifest: Manifest):
    payload = evaluate_tests(manifest, [Path("models/marts/documented.sql")], scope=SCOPE).to_dict()
    assert payload["check"] == "tests"
    assert payload["ok"] is True
    assert payload["scope"] == SCOPE
    assert payload["results"][0]["test_count"] == 2
    assert payload["results"][0]["ok"] is True


# ------------------------------------------------------- failures-only output

_MIXED = [Path("models/marts/documented.sql"), Path("models/marts/no_desc.sql")]


def _text(report, **kwargs) -> str:
    return "\n".join(line for _level, line in report.human_lines(**kwargs))


def test_human_default_shows_only_failures(manifest: Manifest):
    report = evaluate_docs(manifest, _MIXED, scope=SCOPE)  # documented passes, no_desc fails
    text = _text(report)
    assert "no_desc.sql" in text  # the failing model is shown
    assert "documented.sql" not in text  # the passing model is suppressed by default
    assert "model description gaps found" in text  # the verdict still prints


def test_human_show_passes_includes_passing_rows(manifest: Manifest):
    text = _text(evaluate_docs(manifest, _MIXED, scope=SCOPE), show_passes=True)
    assert "documented.sql" in text  # passing row now shown
    assert "no_desc.sql" in text


def test_all_pass_collapses_to_single_verdict_line(manifest: Manifest):
    # Failures-only with nothing failing → no per-item rows, just the verdict.
    report = evaluate_tests(manifest, [Path("models/marts/documented.sql")], scope=SCOPE)
    lines = report.human_lines()
    assert len(lines) == 1
    assert "all selected models tested" in lines[0][1]
