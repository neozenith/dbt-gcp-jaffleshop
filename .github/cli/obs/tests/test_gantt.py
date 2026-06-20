"""Unit tests for the pure Gantt transform (no BigQuery).

The fixture is a hand-built ``dbt_run_results`` slice with seeded ground truth:
4 nodes across 3 threads (incl. ``Thread-10`` to exercise natural lane ordering),
a planted failing test, and a known wall window (05:58:54 → 05:59:05.6 = 11.6s) with
CPU = 2 + 4 + 1.5 + 7.6 = 15.1s.
"""

# Standard Library
import json
from pathlib import Path

# Third Party
import pytest

# Local
from obs import gantt

FIXTURE = Path(__file__).parent / "fixtures" / "run_results.json"


@pytest.fixture
def rows() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def payload(rows) -> dict:
    return gantt.build_gantt_payload(rows, "inv-test-0001", source_label="proj.DS.dbt_run_results")


def test_thread_lanes_sorted_naturally(payload):
    # Thread-10 must sort AFTER Thread-1/2, not lexically before Thread-2.
    assert payload["threads"] == ["Thread-1 (worker)", "Thread-2 (worker)", "Thread-10 (worker)"]


def test_metadata_wall_and_cpu(payload):
    m = payload["metadata"]
    assert m["n_nodes"] == 4
    assert m["n_threads"] == 3
    assert m["wall_secs"] == pytest.approx(11.6, abs=1e-6)
    assert m["cpu_secs"] == pytest.approx(15.1, abs=1e-6)
    # CPU/wall speed-up.
    assert m["speedup"] == pytest.approx(15.1 / 11.6, abs=1e-3)
    assert m["wall_start"] == "2026-06-17T05:58:54Z"
    assert m["wall_end"] == "2026-06-17T05:59:05.600000Z"


def test_start_offsets_relative_to_wall_start(payload):
    by_id = {n["node_id"]: n for n in payload["nodes"]}
    assert by_id["model.jaffle_shop.stg_customers"]["start_offset_secs"] == pytest.approx(0.0)
    # customers starts at 05:58:58 → 4s after wall start.
    assert by_id["model.jaffle_shop.customers"]["start_offset_secs"] == pytest.approx(4.0)


def test_required_four_fields_present_on_every_node(payload):
    for n in payload["nodes"]:
        assert {"thread_id", "node_id", "start", "duration_secs"} <= set(n)


def test_resource_types_collected_and_sorted(payload):
    assert payload["metadata"]["resource_types"] == ["model", "test"]


def test_failing_status_preserved(payload):
    failing = [n for n in payload["nodes"] if n["status"] == "fail"]
    assert len(failing) == 1
    assert failing[0]["node_id"] == "test.jaffle_shop.not_null_stg_customers_id"


def test_empty_rows_raise():
    with pytest.raises(ValueError):
        gantt.build_gantt_payload([], "inv", source_label="x")


# ─── build_bundle (multi-run index + per-run payloads) ───────────────────────


@pytest.fixture
def window_rows(rows) -> list[dict]:
    """Two invocations sharing the fixture's node shape, tagged with invocation_id."""
    older = [{**r, "invocation_id": "inv-OLD"} for r in rows]
    newer = [{**r, "invocation_id": "inv-NEW"} for r in rows]
    return older + newer


@pytest.fixture
def invocations() -> list[dict]:
    return [
        {
            "invocation_id": "inv-NEW",
            "command": "build",
            "threads": 16,
            "run_started_at": "2026-06-18T05:00:00Z",
            "git_sha": "abc123",
            "target_name": "prod",
            "dbt_version": "1.11.10",
            "full_refresh": False,
        },
        {
            "invocation_id": "inv-OLD",
            "command": "build",
            "threads": 4,
            "run_started_at": "2026-06-17T05:00:00Z",
            "git_sha": "def456",
            "target_name": "prod",
            "dbt_version": "1.11.10",
            "full_refresh": False,
        },
    ]


@pytest.fixture
def bundle(invocations, window_rows) -> dict:
    return gantt.build_bundle(invocations, window_rows, source_label="proj.DS.dbt_run_results", days=30)


def test_bundle_has_one_run_per_invocation(bundle):
    assert bundle["metadata"]["n_runs"] == 2
    assert set(bundle["runs"]) == {"inv-OLD", "inv-NEW"}


def test_bundle_index_sorted_newest_first(bundle):
    ids = [e["invocation_id"] for e in bundle["index"]]
    assert ids == ["inv-NEW", "inv-OLD"]


def test_bundle_index_carries_configured_threads(bundle):
    by_id = {e["invocation_id"]: e for e in bundle["index"]}
    assert by_id["inv-NEW"]["configured_threads"] == 16
    assert by_id["inv-OLD"]["configured_threads"] == 4
    # observed lanes come from the fixture (3 distinct thread_ids).
    assert by_id["inv-NEW"]["observed_threads"] == 3


def test_bundle_index_flags_failures(bundle):
    # The fixture plants one failing test, so every run has a failure.
    assert all(e["has_failures"] for e in bundle["index"])


def test_bundle_run_payload_is_a_full_gantt(bundle):
    payload = bundle["runs"]["inv-NEW"]
    assert payload["metadata"]["n_nodes"] == 4
    assert {"thread_id", "node_id", "start", "duration_secs"} <= set(payload["nodes"][0])


def test_bundle_missing_invocation_metadata_tolerated(window_rows):
    # No dbt_invocations rows at all → index still builds, threads/command are None.
    b = gantt.build_bundle([], window_rows, source_label="x", days=7)
    assert b["metadata"]["n_runs"] == 2
    assert all(e["configured_threads"] is None for e in b["index"])
    assert all(e["command"] is None for e in b["index"])
