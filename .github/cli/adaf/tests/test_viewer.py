"""Unit tests for the sdag viewer engine.

The JSON builders are pure (nodes + edges + resolved → Cytoscape dict), so they're tested against
hand-built data. ``load_full_manifest`` and ``write_outputs`` touch the filesystem and are tested with
a real ``tmp_path`` + the real packaged assets — no mocks.
"""

# Standard Library
import json

# Local
from adaf import viewer

# A tiny lineage: source → A → B → X. A/B/S belong to product "prod"; X is unmatched.
_NODES = {
    "model.a": {"unique_id": "model.a", "resource_type": "model", "name": "a"},
    "model.b": {"unique_id": "model.b", "resource_type": "model", "name": "b"},
    "source.s": {"unique_id": "source.s", "resource_type": "source", "name": "s"},
    "model.x": {"unique_id": "model.x", "resource_type": "model", "name": "x"},
}
_EDGES = [("source.s", "model.a"), ("model.a", "model.b"), ("model.b", "model.x")]
_RESOLVED = {"prod": {"model.a", "model.b", "source.s"}}


def _by_id(payload: dict) -> dict:
    return {e["data"]["id"]: e["data"] for e in payload["elements"]}


# ─── full graph ──────────────────────────────────────────────────────────────


def test_full_graph_makes_a_compound_per_selector_plus_unmatched():
    data = _by_id(viewer.build_full_graph_json(_NODES, _EDGES, _RESOLVED))
    assert data["sel::prod"]["kind"] == "selector_compound"
    assert data["sel::prod"]["n_members"] == 3
    assert data[f"sel::{viewer.UNMATCHED_ID}"]["n_members"] == 1  # model.x matched no selector


def test_full_graph_parents_entities_into_their_compound():
    data = _by_id(viewer.build_full_graph_json(_NODES, _EDGES, _RESOLVED))
    assert data["model.a"]["parent"] == "sel::prod"
    assert data["model.x"]["parent"] == f"sel::{viewer.UNMATCHED_ID}"
    assert data["source.s"]["colour"] == viewer.NODE_COLOURS["source"]


def test_full_graph_primary_selector_is_the_smallest_membership():
    # model.a is in BOTH "big" and "small"; the smaller (most specific) selector wins as the parent.
    resolved = {"big": {"model.a", "model.b", "source.s", "model.x"}, "small": {"model.a"}}
    data = _by_id(viewer.build_full_graph_json(_NODES, _EDGES, resolved))
    assert data["model.a"]["parent"] == "sel::small"
    assert set(data["model.a"]["selectors"]) == {"big", "small"}


def test_full_graph_metadata_counts():
    meta = viewer.build_full_graph_json(_NODES, _EDGES, _RESOLVED)["metadata"]
    # compliance defaults to an empty dict when no per-selector compliance is supplied.
    assert meta == {"n_nodes": 4, "n_edges": 3, "n_selectors": 1, "n_unmatched_nodes": 1, "compliance": {}}


# ─── super graph ─────────────────────────────────────────────────────────────


def test_super_graph_collapses_selectors_with_breakdown():
    data = _by_id(viewer.build_super_graph_json(_NODES, _EDGES, _RESOLVED))
    assert data["prod"]["n_members"] == 3
    assert data["prod"]["breakdown"] == {"model": 2, "source": 1}
    assert data[viewer.UNMATCHED_ID]["breakdown"] == {"model": 1}


def test_super_graph_aggregates_only_crossing_edges():
    payload = viewer.build_super_graph_json(_NODES, _EDGES, _RESOLVED)
    super_edges = [e["data"] for e in payload["elements"] if e["data"].get("kind") == "lineage"]
    # Only B→X crosses prod→unmatched; S→A and A→B are internal to prod.
    assert len(super_edges) == 1
    assert (super_edges[0]["source"], super_edges[0]["target"], super_edges[0]["count"]) == (
        "prod",
        viewer.UNMATCHED_ID,
        1,
    )
    assert payload["metadata"]["n_internal_edges_collapsed"] == 2


# ─── load_full_manifest ──────────────────────────────────────────────────────


def test_load_full_manifest_keeps_all_resource_types_and_drops_dangling_edges(tmp_path):
    manifest = {
        "nodes": {
            "model.a": {"resource_type": "model", "name": "a"},
            "test.t": {"resource_type": "test", "name": "t"},  # viewer keeps tests (unlike graph.py)
        },
        "sources": {"source.s": {"resource_type": "source", "name": "s"}},
        "parent_map": {
            "model.a": ["source.s"],
            "test.t": ["model.a"],
            "model.a_extra": ["model.ghost"],  # both endpoints unknown → dropped
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    nodes, edges = viewer.load_full_manifest(path)
    assert set(nodes) == {"model.a", "test.t", "source.s"}  # test kept
    assert ("source.s", "model.a") in edges
    assert ("model.a", "test.t") in edges
    assert all(p in nodes and c in nodes for p, c in edges)  # no dangling edge survived


# ─── write_outputs (real assets + tmp_path) ──────────────────────────────────


def test_write_outputs_emits_four_files_and_substitutes_tokens(tmp_path):
    full = viewer.build_full_graph_json(_NODES, _EDGES, _RESOLVED)
    super_graph = viewer.build_super_graph_json(_NODES, _EDGES, _RESOLVED)
    build_id = viewer.write_outputs(tmp_path, full, super_graph, source_label="unit/test/manifest.json")

    for fname in (viewer.FULL_GRAPH_JSON, viewer.SUPER_GRAPH_JSON, viewer.SDAG_HTML, viewer.SDAG_JS):
        assert (tmp_path / fname).exists()

    js = (tmp_path / viewer.SDAG_JS).read_text(encoding="utf-8")
    assert "{{BUILD_ID}}" not in js and "{{SOURCE}}" not in js  # tokens fully substituted
    assert build_id in js
    assert "unit/test/manifest.json" in js

    meta = json.loads((tmp_path / viewer.FULL_GRAPH_JSON).read_text(encoding="utf-8"))["metadata"]
    assert meta["build_id"] == build_id
    assert meta["source"] == "unit/test/manifest.json"
