"""Unit tests for the data-product system-boundary analysis.

All pure: the boundary classification, the manifest→graph distillation (data-node filtering), and the
report rendering are exercised against hand-built data — no dbt, no warehouse, no mocks. The I/O
seams (``dbt ls`` membership, manifest read) are thin wrappers tested implicitly by the CLI smoke
suite, per the project's "test pure functions with real data" rule.
"""

# Local
from cicd_cli.commands.dataproducts import (
    BoundaryReport,
    BoundaryTestRow,
    MemberRow,
    ProductBoundary,
    SystemBoundaryReport,
)
from cicd_cli.graph import Graph, classify_boundary

# ─── classify_boundary: the four roles ───────────────────────────────────────


def test_classify_four_roles_via_external_edges():
    # A graph where each member exercises one classification through CROSSING edges:
    #   A: external parent (EXT_P)            → inbound
    #   B: only internal parent + child       → internal
    #   C: external child (EXT_C)             → outbound
    #   D: external parent AND external child → both
    members = {"A", "B", "C", "D"}
    edges = [
        ("EXT_P", "A"),  # A consumes data from outside the product
        ("A", "B"),
        ("B", "C"),
        ("C", "EXT_C"),  # C feeds a consumer outside the product
        ("EXT_P", "D"),
        ("D", "EXT_C"),
    ]
    result = classify_boundary(members, edges)

    assert result["A"].classification == "inbound"
    assert result["A"].external_parents == ["EXT_P"]
    assert result["A"].external_children == []

    assert result["B"].classification == "internal"
    assert result["B"].is_boundary is False

    assert result["C"].classification == "outbound"
    assert result["C"].external_children == ["EXT_C"]

    assert result["D"].classification == "both"
    assert result["D"].external_parents == ["EXT_P"]
    assert result["D"].external_children == ["EXT_C"]


def test_classify_topological_root_and_leaf_have_no_external_neighbours():
    # The "no internal parent/child" branch: a true source (no parents at all) is still inbound and a
    # final leaf (no children at all) is still outbound — even though neither has an EXTERNAL neighbour.
    members = {"ROOT", "INNER", "LEAF"}
    edges = [("ROOT", "INNER"), ("INNER", "LEAF")]
    result = classify_boundary(members, edges)

    assert result["ROOT"].classification == "inbound"
    assert result["ROOT"].external_parents == []  # entry by topology, not by a crossing edge
    assert result["INNER"].classification == "internal"
    assert result["LEAF"].classification == "outbound"
    assert result["LEAF"].external_children == []


def test_classify_isolated_member_is_both():
    # A member with no edges at all is simultaneously a root (no internal parent) and a leaf
    # (no internal child), so it lands in `both` — degenerate but well-defined.
    result = classify_boundary({"X"}, [])
    assert result["X"].classification == "both"


# ─── Graph.from_dict: data-node filtering ────────────────────────────────────

# A miniature manifest in dbt's shape: a source → staging → mart chain, a model OUTSIDE the product,
# plus a test and a semantic_model hanging off the mart. Only the four data nodes and the edges
# BETWEEN them must survive; the test/semantic attachments (and their edges) must be dropped.
_MANIFEST = {
    "nodes": {
        "model.shop.stg_a": {"resource_type": "model", "name": "stg_a"},
        "model.shop.mart_a": {"resource_type": "model", "name": "mart_a"},
        "model.shop.external": {"resource_type": "model", "name": "external"},
        # Two tests on stg_a, one on the SOURCE raw_a — counted via depends_on.nodes (not parent_map).
        "test.shop.t_stg_a_1": {"resource_type": "test", "depends_on": {"nodes": ["model.shop.stg_a"]}},
        "test.shop.t_stg_a_2": {"resource_type": "test", "depends_on": {"nodes": ["model.shop.stg_a"]}},
        "test.shop.t_raw_a": {"resource_type": "test", "depends_on": {"nodes": ["source.shop.ecom.raw_a"]}},
        "semantic_model.shop.sm_a": {"resource_type": "semantic_model", "name": "sm_a"},
    },
    "sources": {
        "source.shop.ecom.raw_a": {"resource_type": "source", "name": "raw_a"},
    },
    "parent_map": {
        "source.shop.ecom.raw_a": [],
        "model.shop.stg_a": ["source.shop.ecom.raw_a"],
        "model.shop.mart_a": ["model.shop.stg_a"],
        "model.shop.external": ["model.shop.stg_a"],
        "test.shop.t_stg_a_1": ["model.shop.stg_a"],
        "test.shop.t_stg_a_2": ["model.shop.stg_a"],
        "test.shop.t_raw_a": ["source.shop.ecom.raw_a"],
        "semantic_model.shop.sm_a": ["model.shop.mart_a"],
    },
}


def test_graph_counts_tests_per_data_node_including_sources():
    graph = Graph.from_dict(_MANIFEST)
    counts = {uid: info.test_count for uid, info in graph.nodes().items()}
    assert counts["model.shop.stg_a"] == 2  # two tests depend on stg_a
    assert counts["source.shop.ecom.raw_a"] == 1  # a source can carry a test too
    assert counts["model.shop.mart_a"] == 0  # untested


def test_graph_keeps_only_data_nodes():
    graph = Graph.from_dict(_MANIFEST)
    assert set(graph.nodes()) == {
        "source.shop.ecom.raw_a",
        "model.shop.stg_a",
        "model.shop.mart_a",
        "model.shop.external",
    }
    raw = graph.info("source.shop.ecom.raw_a")
    assert raw is not None and raw.resource_type == "source"


def test_graph_drops_edges_to_non_data_nodes():
    graph = Graph.from_dict(_MANIFEST)
    edges = set(graph.edges())
    assert ("source.shop.ecom.raw_a", "model.shop.stg_a") in edges
    assert ("model.shop.stg_a", "model.shop.mart_a") in edges
    assert ("model.shop.stg_a", "model.shop.external") in edges
    # The mart→test and mart→semantic_model edges must NOT survive (attachments, not data lineage).
    assert all("test." not in c and "semantic_model." not in c for _p, c in edges)


def test_graph_classify_marks_external_as_boundary():
    # With the product = {raw_a, stg_a, mart_a}, stg_a feeds `external` (outside the product) → it is
    # an outbound boundary; raw_a is the inbound source; mart_a is an outbound leaf.
    graph = Graph.from_dict(_MANIFEST)
    product = {"source.shop.ecom.raw_a", "model.shop.stg_a", "model.shop.mart_a"}
    result = classify_boundary(product, graph.edges())
    assert result["source.shop.ecom.raw_a"].classification == "inbound"
    assert result["model.shop.stg_a"].classification == "outbound"
    assert result["model.shop.stg_a"].external_children == ["model.shop.external"]
    assert result["model.shop.mart_a"].classification == "outbound"


# ─── BoundaryReport rendering ────────────────────────────────────────────────


def _product() -> ProductBoundary:
    return ProductBoundary(
        product="supply",
        description="supply side",
        rows=[
            MemberRow("source.shop.raw_a", "raw_a", "source", "inbound", [], []),
            MemberRow("model.shop.stg_a", "stg_a", "model", "outbound", [], ["model.shop.order_items"]),
            MemberRow("model.shop.mid_a", "mid_a", "model", "internal", [], []),
        ],
    )


def _text(report: BoundaryReport, **kwargs) -> str:
    return "\n".join(line for _level, line in report.human_lines(**kwargs))


def test_report_is_always_ok_and_counts_are_correct():
    report = BoundaryReport([_product()], scope="1 data product(s)")
    assert report.ok is True  # descriptive analysis never gates
    payload = report.to_dict()
    assert payload["products"][0]["counts"] == {"inbound": 1, "outbound": 1, "both": 0, "internal": 1}
    assert payload["products"][0]["n_members"] == 3


def test_report_default_hides_internal_nodes():
    text = _text(BoundaryReport([_product()], scope="x"))
    assert "raw_a" in text  # inbound boundary shown
    assert "stg_a" in text  # outbound boundary shown
    assert "mid_a" not in text  # internal node hidden by default
    assert "1 internal node(s) hidden" in text


def test_report_show_passes_reveals_internal_nodes():
    text = _text(BoundaryReport([_product()], scope="x"), show_passes=True)
    assert "mid_a" in text  # internal node now shown


def test_report_external_child_count_is_surfaced():
    text = _text(BoundaryReport([_product()], scope="x"))
    assert "1 ext child(ren)" in text  # stg_a's crossing edge to order_items


def test_report_empty_is_ok():
    report = BoundaryReport([], scope="none")
    assert report.ok is True
    assert "no data products" in _text(report)


# ─── check system-boundaries: the gate ───────────────────────────────────────


def _gate_rows() -> list[BoundaryTestRow]:
    # supply: an untested inbound source (fails) + a tested outbound model (passes).
    # demand: the SAME source shows up again (shared, still untested) — flagged per product.
    return [
        BoundaryTestRow("supply", "source.shop.raw_a", "raw_a", "source", "inbound", 0),
        BoundaryTestRow("supply", "model.shop.stg_a", "stg_a", "model", "outbound", 2),
        BoundaryTestRow("demand", "source.shop.raw_a", "raw_a", "source", "inbound", 0),
    ]


def _gate_text(report: SystemBoundaryReport, **kwargs) -> str:
    return "\n".join(line for _level, line in report.human_lines(**kwargs))


def test_gate_fails_when_a_boundary_node_has_no_tests():
    report = SystemBoundaryReport("x", _gate_rows())
    assert report.ok is False  # untested inbound source → fail
    assert report.summary() == "2 boundary node(s) untested"


def test_gate_passes_when_all_boundary_nodes_tested():
    rows = [BoundaryTestRow("supply", "model.shop.stg_a", "stg_a", "model", "outbound", 2)]
    report = SystemBoundaryReport("x", rows)
    assert report.ok is True
    assert "all 1 boundary node(s) have ≥1 test" in _gate_text(report)


def test_gate_default_shows_only_failures_grouped_by_product():
    text = _gate_text(SystemBoundaryReport("x", _gate_rows()))
    assert "raw_a (source, inbound)" in text  # the untested inbound boundary is shown
    assert "no tests on this boundary node" in text
    assert "stg_a" not in text  # the tested (passing) boundary node is hidden by default
    assert "supply" in text and "demand" in text  # both products' at-risk edges surfaced


def test_gate_show_passes_includes_tested_nodes():
    text = _gate_text(SystemBoundaryReport("x", _gate_rows()), show_passes=True)
    assert "stg_a (model, outbound) — 2 test(s)" in text


def test_gate_to_dict_carries_every_row_with_ok():
    payload = SystemBoundaryReport("x", _gate_rows()).to_dict()
    assert payload["check"] == "system-boundaries"
    assert payload["ok"] is False
    assert [r["ok"] for r in payload["results"]] == [False, False, True]  # sorted: demand/raw, supply/raw, supply/stg


def test_gate_empty_is_ok():
    report = SystemBoundaryReport("x", [])
    assert report.ok is True
    assert "no boundary nodes" in report.summary()


def test_gate_error_state_fails_and_renders_without_crashing():
    # This is the shape check-all produces when membership can't be resolved (bad selectors / dbt-ls
    # error): a failing report that still renders, so the aggregate keeps running.
    report = SystemBoundaryReport("all data products", [], error="`dbt ls --selector supply` failed")
    assert report.ok is False
    assert "could not resolve data products" in report.summary()
    text = _gate_text(report)
    assert "dbt ls --selector supply` failed" in text
    assert report.to_dict()["error"] == "`dbt ls --selector supply` failed"
