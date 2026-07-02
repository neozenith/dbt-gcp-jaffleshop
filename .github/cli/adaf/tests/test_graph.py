"""Unit tests for the lineage graph boundary classification — pure (synthetic manifest, no dbt)."""

# Standard Library
import json

# First Party
from adaf.dbt.graph import BOTH, INBOUND, INNER, OUTBOUND, Graph, load_graph


def _manifest() -> dict:
    """A hand-built manifest. The data product (member set) is {ext_in -> a -> b -> c -> ext_out}
    plus an island ``d`` whose only neighbour is the interior node ``b``.

        ext_in --> a --> b --> c --> ext_out
                         ^
                         |
                         d  (member, only edge is to interior b)

    Members: a, b, c, d. Externals: ext_in (upstream of a), ext_out (downstream of c).
    Expected: a=inbound (parent ext_in), c=outbound (child ext_out), b=inner; d=inbound because it
    is a topological root (no parent inside the product — an entry point).
    """
    return {
        "nodes": {
            "model.p.a": {"resource_type": "model", "name": "a"},
            "model.p.b": {"resource_type": "model", "name": "b"},
            "model.p.c": {"resource_type": "model", "name": "c"},
            "model.p.d": {"resource_type": "model", "name": "d"},
            "model.p.ext_out": {"resource_type": "model", "name": "ext_out"},
        },
        "sources": {
            "source.p.ext_in": {"resource_type": "source", "name": "ext_in"},
        },
        # parent_map: child -> [parents]
        "parent_map": {
            "source.p.ext_in": [],
            "model.p.a": ["source.p.ext_in"],
            "model.p.b": ["model.p.a", "model.p.d"],
            "model.p.c": ["model.p.b"],
            "model.p.d": [],
            "model.p.ext_out": ["model.p.c"],
        },
    }


MEMBERS = {"model.p.a", "model.p.b", "model.p.c", "model.p.d"}


def test_from_dict_collects_all_node_ids() -> None:
    g = Graph.from_dict(_manifest())
    assert MEMBERS <= g.nodes()
    assert "source.p.ext_in" in g.nodes()
    assert "model.p.ext_out" in g.nodes()


def test_classify_four_labels() -> None:
    result = Graph.from_dict(_manifest()).classify(MEMBERS)
    assert result == {
        "model.p.a": INBOUND,  # parent source.p.ext_in is outside the set
        "model.p.b": INNER,  # parents a,d and child c all inside the set
        "model.p.c": OUTBOUND,  # child model.p.ext_out is outside the set
        "model.p.d": INBOUND,  # topological root (no parent inside the product) → entry point
    }


def test_attribute_explains_each_label() -> None:
    attr = Graph.from_dict(_manifest()).attribute(MEMBERS)
    # a is inbound BECAUSE its parent source.p.ext_in is external — the attribution names it.
    assert attr["model.p.a"]["boundary"] == INBOUND
    ext_p = next(r for r in attr["model.p.a"]["attribution"] if r["code"] == "external_parent")
    assert ext_p["nodes"] == ["source.p.ext_in"] and ext_p["axis"] == INBOUND
    # b is inner — attribution records the "interior" reason.
    assert attr["model.p.b"]["boundary"] == INNER
    assert any(r["code"] == "interior" for r in attr["model.p.b"]["attribution"])
    # c is outbound BECAUSE its child model.p.ext_out is external.
    ext_c = next(r for r in attr["model.p.c"]["attribution"] if r["code"] == "external_child")
    assert ext_c["nodes"] == ["model.p.ext_out"]
    # d is a topological root (no in-product parent) -> inbound via that reason.
    assert any(r["code"] == "topological_root" for r in attr["model.p.d"]["attribution"])


def test_classify_both_when_external_parent_and_child() -> None:
    # A single-member product: every neighbour is external, so the lone member is `both`.
    result = Graph.from_dict(_manifest()).classify({"model.p.b"})
    assert result == {"model.p.b": BOTH}


def test_edges_reconstructed_from_depends_on_without_parent_map() -> None:
    data = {
        "nodes": {
            "model.p.x": {"resource_type": "model", "name": "x", "depends_on": {"nodes": ["model.p.upstream"]}},
            "model.p.upstream": {"resource_type": "model", "name": "upstream", "depends_on": {"nodes": []}},
        }
    }
    g = Graph.from_dict(data)
    assert ("model.p.upstream", "model.p.x") in g.edges()
    # upstream is a topological root (entry) and x is a topological leaf (exit), even though their
    # shared edge is internal: upstream→inbound, x→outbound.
    assert g.classify({"model.p.x", "model.p.upstream"}) == {"model.p.x": OUTBOUND, "model.p.upstream": INBOUND}
    # Scope the product to x alone -> parent upstream external (inbound) AND x is a leaf (outbound) -> both.
    assert g.classify({"model.p.x"}) == {"model.p.x": BOTH}


def test_only_models_classified_source_is_edge_not_subject() -> None:
    """Only MODELS are boundary subjects. A source the model reads is NOT classified — it is the
    external edge that makes the reading model inbound. And a model→test edge is dropped entirely."""
    data = {
        "nodes": {
            "model.p.stg": {"resource_type": "model", "name": "stg"},
            "test.p.not_null_stg": {"resource_type": "test", "name": "nn", "depends_on": {"nodes": ["model.p.stg"]}},
        },
        "sources": {
            "source.p.raw": {"resource_type": "source", "name": "raw"},
        },
        "parent_map": {
            "source.p.raw": [],
            "model.p.stg": ["source.p.raw"],
            "test.p.not_null_stg": ["model.p.stg"],  # a test child — must be filtered out
        },
    }
    g = Graph.from_dict(data)
    assert "test.p.not_null_stg" not in g.nodes()  # tests are not part of the backbone
    # Even with the source + test in the member set, ONLY the model is classified.
    result = g.classify({"source.p.raw", "model.p.stg", "test.p.not_null_stg"})
    assert result == {
        # stg reads a source (external parent → inbound) and its only child was a test (no model
        # child → outbound leaf) → both. The SOURCE is not a subject; it is the inbound edge.
        "model.p.stg": BOTH,
    }


def test_model_feeding_external_exposure_is_outbound() -> None:
    """An exposure is a downstream consumer: a model that feeds an exposure OUTSIDE the product is an
    outbound boundary, even when it also has an in-product model child. Exposures are never classified."""
    data = {
        "nodes": {
            "model.p.stg": {"resource_type": "model", "name": "stg"},
            "model.p.mart": {"resource_type": "model", "name": "mart", "depends_on": {"nodes": ["model.p.stg"]}},
            "model.p.inner": {"resource_type": "model", "name": "inner", "depends_on": {"nodes": ["model.p.mart"]}},
        },
        "exposures": {
            "exposure.p.dash": {"resource_type": "exposure", "name": "dash", "depends_on": {"nodes": ["model.p.mart"]}},
        },
        "parent_map": {
            "model.p.stg": [],
            "model.p.mart": ["model.p.stg"],
            "model.p.inner": ["model.p.mart"],
            "exposure.p.dash": ["model.p.mart"],  # the model -> exposure edge
        },
    }
    g = Graph.from_dict(data)
    assert "exposure.p.dash" in g.nodes()  # the exposure IS in the boundary graph (as an edge endpoint)
    result = g.classify({"model.p.stg", "model.p.mart", "model.p.inner"})
    assert "exposure.p.dash" not in result  # exposures are edges, never classified
    assert result["model.p.mart"] == OUTBOUND  # has an in-product child (inner) AND an external exposure
    # Without the exposure, mart would be INNER (internal parent stg, internal child inner).
    assert g.classify({"model.p.stg", "model.p.inner"}).get("model.p.mart") is None


def test_load_graph_reads_from_disk(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")
    g = load_graph(path)
    assert g.classify(MEMBERS)["model.p.a"] == INBOUND
