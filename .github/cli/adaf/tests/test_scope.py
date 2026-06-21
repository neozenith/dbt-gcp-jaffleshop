"""Unit tests for the product-scope lineage hop expansion (``adaf.dbt.scope``) — pure, no dbt."""

# First Party
from adaf.dbt.manifest_view import ManifestView
from adaf.dbt.scope import UNBOUNDED, Selection, _expand_hops, describe


def _chain_view() -> ManifestView:
    """A straight lineage: source.s -> a -> b -> c -> d (all models except the source)."""
    data = {
        "nodes": {
            "model.p.a": {"resource_type": "model", "name": "a"},
            "model.p.b": {"resource_type": "model", "name": "b"},
            "model.p.c": {"resource_type": "model", "name": "c"},
            "model.p.d": {"resource_type": "model", "name": "d"},
        },
        "sources": {"source.p.s": {"resource_type": "source", "name": "s"}},
        "parent_map": {
            "source.p.s": [],
            "model.p.a": ["source.p.s"],
            "model.p.b": ["model.p.a"],
            "model.p.c": ["model.p.b"],
            "model.p.d": ["model.p.c"],
        },
    }
    return ManifestView.from_dict(data)


def test_expand_no_hops_returns_base_unchanged() -> None:
    view = _chain_view()
    assert _expand_hops({"model.p.c"}, view, upstream=None, downstream=None) == {"model.p.c"}


def test_expand_zero_hops_is_just_base() -> None:
    view = _chain_view()
    assert _expand_hops({"model.p.c"}, view, upstream=0, downstream=0) == {"model.p.c"}


def test_expand_one_hop_each_direction() -> None:
    view = _chain_view()
    assert _expand_hops({"model.p.c"}, view, upstream=1, downstream=None) == {"model.p.b", "model.p.c"}
    assert _expand_hops({"model.p.c"}, view, upstream=None, downstream=1) == {"model.p.c", "model.p.d"}


def test_expand_n_hops_upstream() -> None:
    view = _chain_view()
    # 2 hops up from c: b (hop1) then a (hop2). The source at hop3 is out of range AND not a model.
    assert _expand_hops({"model.p.c"}, view, upstream=2, downstream=None) == {"model.p.a", "model.p.b", "model.p.c"}


def test_expand_unbounded_includes_source_ancestors() -> None:
    view = _chain_view()
    # All ancestors of c: b, a, AND source.s. Hop expansion keeps non-model backbone nodes — dropping
    # sources here was the bug that made `--upstream` a no-op for source-fed products.
    assert _expand_hops({"model.p.c"}, view, upstream=UNBOUNDED, downstream=None) == {
        "model.p.a",
        "model.p.b",
        "model.p.c",
        "source.p.s",
    }


def test_expand_both_directions_unbounded() -> None:
    view = _chain_view()
    assert _expand_hops({"model.p.c"}, view, upstream=UNBOUNDED, downstream=UNBOUNDED) == {
        "source.p.s",
        "model.p.a",
        "model.p.b",
        "model.p.c",
        "model.p.d",
    }


# ─── describe(): the human scope label ─────────────────────────────────────────


def test_describe_changed_only_with_selector() -> None:
    sel = Selection(selector="demand")
    assert describe(sel) == "changed models vs main that are also in selector:demand"


def test_describe_all_with_hops_and_defer() -> None:
    sel = Selection(selector="demand", all_models=True, upstream=1, downstream=UNBOUNDED, defer=True, defer_ref="main")
    label = describe(sel)
    assert "all models that are also in selector:demand" in label
    assert "1 hop upstream" in label
    assert "all downstream" in label
    assert "(defer to main)" in label
