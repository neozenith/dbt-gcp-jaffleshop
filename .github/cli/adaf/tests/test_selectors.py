"""Unit tests for selectors.yml parsing + lineage hop expansion — pure, no dbt/warehouse."""

# Third Party
import pytest

# First Party
from adaf.dbt.manifest_view import ManifestView
from adaf.dbt.selection import UNBOUNDED, _expand_hops
from adaf.dbt.selectors import _uses_state, load_selectors, selector_names


@pytest.mark.parametrize(
    "definition,expected",
    [
        ("tag:demand_au", False),
        ("state:modified", True),
        ("state:modified+", True),
        ({"method": "state", "value": "modified"}, True),
        ({"method": "tag", "value": "demand_au"}, False),
        ({"union": [{"method": "tag", "value": "a"}, {"method": "state", "value": "modified"}]}, True),
        ({"union": [{"method": "tag", "value": "a"}, {"method": "tag", "value": "b"}]}, False),
        ({"intersection": ["tag:x", "state:modified"]}, True),
        (None, False),
        ([], False),
    ],
)
def test_uses_state(definition: object, expected: bool) -> None:
    assert _uses_state(definition) is expected


def test_load_selectors_reads_name_desc_and_state(tmp_path) -> None:
    p = tmp_path / "selectors.yml"
    p.write_text(
        "selectors:\n"
        "  - name: demand\n"
        "    description: Demand models\n"
        "    definition: tag:demand_au\n"
        "  - name: changed\n"
        "    definition:\n"
        "      method: state\n"
        "      value: modified\n",
        encoding="utf-8",
    )
    out = load_selectors(p)
    assert out == [
        ("demand", "Demand models", False, "tag:demand_au"),
        ("changed", "", True, "method: state\nvalue: modified"),
    ]
    assert selector_names(p) == ["demand", "changed"]


def test_load_selectors_missing_file_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_selectors(tmp_path / "nope.yml")


def test_load_selectors_missing_name_raises(tmp_path) -> None:
    p = tmp_path / "selectors.yml"
    p.write_text("selectors:\n  - definition: tag:x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_selectors(p)


# ─── lineage hop expansion (_expand_hops) ──────────────────────────────────────


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
    # sources here was the bug that made `--upstream` a no-op for source-fed products. resolve_model_ids
    # re-filters to models at its own boundary; resolve_scope_ids keeps the source.
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
