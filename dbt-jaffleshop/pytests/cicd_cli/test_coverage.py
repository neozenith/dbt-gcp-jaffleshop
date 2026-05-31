# Standard Library
from pathlib import Path

# Local
from cicd_cli.commands.coverage import evaluate_docs, evaluate_tests
from cicd_cli.manifest import Manifest

SCOPE = "changed models vs main"

# --------------------------------------------------------------------------- docs


def test_docs_flags_undocumented_column(manifest: Manifest):
    report = evaluate_docs(manifest, [Path("models/staging/partial_cols.sql")], scope=SCOPE)
    row = report.rows[0]
    assert row.has_description is True
    assert row.undocumented_columns == ["blank"]
    assert row.ok is False
    assert report.ok is False


def test_docs_no_columns_flag_relaxes_to_model_level(manifest: Manifest):
    report = evaluate_docs(
        manifest, [Path("models/staging/partial_cols.sql")], scope=SCOPE, require_columns=False
    )
    assert report.rows[0].ok is True
    assert report.ok is True


def test_docs_flags_missing_model_description(manifest: Manifest):
    report = evaluate_docs(manifest, [Path("models/marts/no_desc.sql")], scope=SCOPE)
    assert report.rows[0].has_description is False
    assert report.ok is False


def test_docs_model_absent_from_manifest_fails(manifest: Manifest):
    report = evaluate_docs(manifest, [Path("models/marts/ghost.sql")], scope=SCOPE)
    assert report.rows[0].in_manifest is False
    assert report.ok is False


def test_docs_fully_documented_model_passes(manifest: Manifest):
    report = evaluate_docs(manifest, [Path("models/marts/documented.sql")], scope=SCOPE)
    assert report.ok is True


def test_docs_empty_changeset_is_ok(manifest: Manifest):
    report = evaluate_docs(manifest, [], scope=SCOPE)
    assert report.rows == []
    assert report.ok is True


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
