# Standard Library
from pathlib import Path

# Local
from adaf.commands.coverage import evaluate_columns, evaluate_docs, evaluate_tests
from adaf.commands.dataproducts import BoundaryTestRow, SystemBoundaryReport
from adaf.utils.formatting import markdown_summary


def test_markdown_summary_is_a_table_with_status_and_detail(manifest, catalog):
    docs = evaluate_docs(manifest, [Path("models/marts/no_desc.sql")], scope="all models")  # fails
    columns = evaluate_columns(manifest, catalog, [Path("models/marts/documented.sql")], scope="all models")  # passes
    tests = evaluate_tests(manifest, [Path("models/marts/documented.sql")], scope="all models")  # passes

    md = markdown_summary([docs, columns, tests], scope="all models")

    assert "| Check | Status | Detail |" in md
    assert "_Scope: all models_" in md
    assert "`docs`" in md and "❌ fail" in md
    assert "`doc-columns`" in md and "1/1 columns documented" in md  # check label + summary() detail
    assert "`tests`" in md and "✅ pass" in md
    assert "one or more checks failed" in md  # overall = fail because docs failed


def test_markdown_summary_all_pass_header(manifest):
    tests = evaluate_tests(manifest, [Path("models/marts/documented.sql")], scope="s")
    md = markdown_summary([tests], scope="s")
    assert "all checks passed" in md


def test_markdown_summary_includes_system_boundaries_row(manifest):
    # check all now folds system-boundaries into the aggregate; its row must render in the table with
    # the gate's own summary() detail (and force the overall verdict to fail when a boundary is untested).
    tests = evaluate_tests(manifest, [Path("models/marts/documented.sql")], scope="s")  # passes
    sysbound = SystemBoundaryReport(
        "all data products",
        [BoundaryTestRow("supply", "source.raw_a", "raw_a", "source", "inbound", 0)],  # untested → fail
    )
    md = markdown_summary([tests, sysbound], scope="all models")
    assert "`system-boundaries`" in md
    assert "1 boundary node(s) under-protected" in md  # the gate's summary() detail
    assert "one or more checks failed" in md
