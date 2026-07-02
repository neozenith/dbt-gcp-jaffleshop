"""Viewer data-contract tests — the JSON the front-end (sdag.js) depends on. Pure, no dbt/browser.

Covers the two viewer-side facts the node-type toggle + boundary-mirror in sdag.js rely on:
* exposures are present as display nodes AND as model->exposure edges (so the JS boundary classifier
  can read a model feeding an external exposure as outbound, and the type toggle can hide/show them);
* the per-selector compliance embedded in ``full_graph.json`` carries the PARTIAL per-node
  ``compliance_pct`` the partial ring is driven from.
"""

# First Party
from adaf.dbt.manifest_view import ManifestView
from adaf.sdag.annotations import compute_compliance
from adaf.sdag.viewer import build_full_graph_json, display_graph
from adaf.suppression import Suppressions


def _manifest() -> dict:
    return {
        "nodes": {
            "model.p.stg": {"resource_type": "model", "name": "stg", "original_file_path": "models/stg.sql"},
            "model.p.fct": {
                "resource_type": "model",
                "name": "fct",
                "original_file_path": "models/fct.sql",
                "config": {"contract": {"enforced": True}},
            },
        },
        "sources": {"source.p.raw": {"resource_type": "source", "name": "raw"}},
        "exposures": {"exposure.p.dash": {"name": "dash", "depends_on": {"nodes": ["model.p.fct"]}}},
        "semantic_models": {},
        "parent_map": {
            "source.p.raw": [],
            "model.p.stg": ["source.p.raw"],
            "model.p.fct": ["model.p.stg"],
            "exposure.p.dash": ["model.p.fct"],  # the model -> exposure edge
        },
    }


def test_display_graph_includes_exposures_as_nodes_and_edges() -> None:
    nodes, edges = display_graph(ManifestView.from_dict(_manifest()))
    assert nodes["exposure.p.dash"]["resource_type"] == "exposure"
    assert ("model.p.fct", "exposure.p.dash") in edges  # the model -> exposure edge survives


def test_full_graph_embeds_partial_per_node_compliance_pct() -> None:
    view = ManifestView.from_dict(_manifest())
    members = {"source.p.raw", "model.p.stg", "model.p.fct"}
    compliance = {"prod": compute_compliance(view, members, Suppressions())}
    nodes, edges = display_graph(view)
    blob = build_full_graph_json(nodes, edges, {"prod": members}, compliance)
    ann = blob["metadata"]["compliance"]["prod"]["annotations"]
    # fct (outbound) is annotated and carries a numeric per-node compliance_pct (the partial ring source).
    assert "compliance_pct" in ann["model.p.fct"]
    assert isinstance(ann["model.p.fct"]["compliance_pct"], (int, float))
    # The source is NOT a boundary subject -> never annotated.
    assert "source.p.raw" not in ann
