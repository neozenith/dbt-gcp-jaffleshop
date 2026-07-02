"""Unit tests for the run-results artifact seam (`adaf.dbt.runresults`)."""

# Standard Library
import json
from pathlib import Path
from typing import Any

# Third Party
import pytest

# First Party
from adaf.dbt import runresults

_RUN_RESULTS = {
    "metadata": {"generated_at": "2026-06-24T00:00:00Z"},
    "elapsed_time": 12.5,
    "results": [
        {"unique_id": "model.p.a", "status": "success"},
        {"unique_id": "test.p.t", "status": "fail", "failures": 3},
        {"not": "a valid entry"},  # skipped, not faked
    ],
}


def test_load_run_results_json_file(tmp_path: Path) -> None:
    path = tmp_path / "run_results.json"
    path.write_text(json.dumps(_RUN_RESULTS), encoding="utf-8")
    rr = runresults.load_run_results(path)
    assert rr is not None
    assert rr.elapsed_time == 12.5
    assert [r.unique_id for r in rr.results] == ["model.p.a", "test.p.t"]  # malformed entry dropped
    assert rr.results[1].failures == 3


def test_load_run_results_missing_is_none(tmp_path: Path) -> None:
    assert runresults.load_run_results(tmp_path / "nope.json") is None


def test_load_run_results_dir_prefers_json(tmp_path: Path) -> None:
    (tmp_path / "run_results.json").write_text(json.dumps(_RUN_RESULTS), encoding="utf-8")
    rr = runresults.load_run_results(tmp_path)  # a directory
    assert rr is not None and len(rr.results) == 2


def test_load_run_results_empty_dir_is_none(tmp_path: Path) -> None:
    assert runresults.load_run_results(tmp_path) is None


def _write_fusion_run(target: Path, duckdb: Any) -> None:
    """A tiny Fusion run set matching the VERIFIED layout: a results table (two invocations — an older
    one that must be excluded, and the latest build) + the build's invocation row. Extra columns are
    included to prove the reader projects only what it needs."""
    results_pq = target / "metadata/run/results/v1_0.parquet"
    inv_pq = target / "metadata/run/invocations/v1_1.parquet"
    results_pq.parent.mkdir(parents=True, exist_ok=True)
    inv_pq.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(database=":memory:")
    try:
        con.execute(
            "CREATE TABLE r (invocation_id VARCHAR, unique_id VARCHAR, status VARCHAR, message VARCHAR, "
            "failures BIGINT, execution_time VARCHAR, ingested_at TIMESTAMPTZ)"
        )
        con.execute("INSERT INTO r VALUES ('inv-old','model.p.old','success',NULL,NULL,'0.1', now() - INTERVAL 1 HOUR)")
        con.execute("INSERT INTO r VALUES ('inv-build','model.p.a','error','boom',NULL,'1.0', now())")
        con.execute("INSERT INTO r VALUES ('inv-build','test.p.t','fail','3 failing rows',3,'0.2', now())")
        con.execute(f"COPY r TO '{results_pq}' (FORMAT PARQUET)")
        con.execute(
            "CREATE TABLE i (invocation_id VARCHAR, command VARCHAR, elapsed_secs VARCHAR, ingested_at TIMESTAMPTZ)"
        )
        con.execute("INSERT INTO i VALUES ('inv-build','build','2.5', now())")
        con.execute(f"COPY i TO '{inv_pq}' (FORMAT PARQUET)")
    finally:
        con.close()


def test_load_run_results_reads_fusion_parquet(tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")  # supplied by `make test` via --extra fusion
    target = tmp_path / "target"
    _write_fusion_run(target, duckdb)
    rr = runresults.load_run_results(target)  # a directory ⇒ the parquet set wins
    assert rr is not None
    assert rr.elapsed_time == 2.5  # from the build invocation
    assert rr.generated_at is not None
    by_id = {r.unique_id: r for r in rr.results}
    assert set(by_id) == {"model.p.a", "test.p.t"}  # the OLD invocation's row is excluded
    assert by_id["model.p.a"].status == "error"
    assert by_id["test.p.t"].failures == 3


def test_result_message_fallbacks() -> None:
    assert runresults.result_message(runresults.Result("x", "fail", message="boom")) == "boom"
    assert runresults.result_message(runresults.Result("x", "fail", failures=2)) == "2 failing rows"
    assert "No additional" in runresults.result_message(runresults.Result("x", "pass"))


def test_status_str_normalises() -> None:
    assert runresults.status_str("Fail") == "fail"
    assert runresults.status_str(None) == "unknown"
