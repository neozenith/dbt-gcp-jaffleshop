"""Faithful ``state:modified`` calculator tests (`adaf.dbt.state_modified`).

Pure functions over hand-built manifest dicts — no dbt, no mocks (project rule). Each case seeds a
single known mutation so a failure names the exact facet that drifted, mirroring how the eval suite
scores against ``dbt ls --select state:modified`` as the oracle.
"""

# Standard Library
from typing import Any

# Third Party
import pytest

# First Party
from adaf.dbt.state_modified import (
    State,
    StateModified,
    modified,
    modified_model_paths,
    modified_model_reasons,
    modified_plus,
)


def _model(uid: str, **over: Any) -> dict[str, Any]:
    """A minimal manifest model node with sane defaults; ``over`` patches any field."""
    node: dict[str, Any] = {
        "unique_id": uid,
        "resource_type": "model",
        "name": uid.split(".")[-1],
        "original_file_path": f"models/{uid.split('.')[-1]}.sql",
        "raw_code": "select 1",
        "fqn": ["proj", uid.split(".")[-1]],
        "unrendered_config": {"materialized": "view"},
        "config": {},
        "columns": {},
        "description": "",
        "depends_on": {"nodes": [], "macros": []},
        "contract": {"enforced": False, "checksum": None},
        "access": "protected",
        "latest_version": None,
        "deprecation_date": None,
    }
    node.update(over)
    return node


def _manifest(nodes: list[dict[str, Any]], *, macros: dict[str, Any] | None = None, sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Assemble a manifest dict from node/source/macro lists (parent edges via ``depends_on.nodes``)."""
    return {
        "nodes": {n["unique_id"]: n for n in nodes},
        "sources": {s["unique_id"]: s for s in (sources or [])},
        "macros": macros or {},
    }


# ── single-facet detection: one mutation -> one reason ───────────────────────────────────────────
@pytest.mark.parametrize(
    "patch,expected",
    [
        ({"raw_code": "select 2"}, ["body"]),
        ({"unrendered_config": {"materialized": "table"}}, ["config"]),
        ({"unrendered_config": {"materialized": "view", "schema": "other"}}, ["relation"]),  # schema is a relation facet, NOT config
        ({"fqn": ["proj", "renamed"]}, ["fqn"]),
        ({"contract": {"enforced": True, "checksum": "abc"}}, ["contract"]),
        ({"access": "public"}, ["ref_representation"]),
    ],
)
def test_single_facet_reasons(patch: dict[str, Any], expected: list[str]) -> None:
    base = _manifest([_model("model.proj.a")])
    cur = _manifest([_model("model.proj.a", **patch)])
    assert modified(base, cur) == {"model.proj.a": expected}


def test_unchanged_is_empty() -> None:
    base = _manifest([_model("model.proj.a")])
    cur = _manifest([_model("model.proj.a")])
    assert modified(base, cur) == {}


def test_persisted_description_only_counts_when_persist_docs_on() -> None:
    # description change with NO persist_docs ⇒ not modified.
    base = _manifest([_model("model.proj.a", description="old")])
    cur = _manifest([_model("model.proj.a", description="new")])
    assert modified(base, cur) == {}
    # same change WITH persist_docs.relation ⇒ flagged.
    base_p = _manifest([_model("model.proj.a", description="old", config={"persist_docs": {"relation": True}})])
    cur_p = _manifest([_model("model.proj.a", description="new", config={"persist_docs": {"relation": True}})])
    assert modified(base_p, cur_p) == {"model.proj.a": ["persisted_descriptions"]}


# ── new / removed handling ───────────────────────────────────────────────────────────────────────
def test_new_model_is_modified() -> None:
    base = _manifest([])
    cur = _manifest([_model("model.proj.a")])
    assert modified(base, cur) == {"model.proj.a": ["new"]}


def test_removed_model_is_not_emitted() -> None:
    base = _manifest([_model("model.proj.a")])
    cur = _manifest([])
    assert modified(base, cur) == {}


def test_new_source_is_not_modified() -> None:
    # dbt quirk: SourceDefinition.same_contents(None) is True ⇒ a brand-new source is NOT flagged.
    src = {"unique_id": "source.proj.s.t", "resource_type": "source", "fqn": ["proj", "s", "t"], "unrendered_config": {}}
    assert modified(_manifest([]), _manifest([], sources=[src])) == {}


# ── seeds compare by checksum ────────────────────────────────────────────────────────────────────
def test_seed_uses_checksum_not_raw_code() -> None:
    seed = lambda cs: {  # noqa: E731
        "unique_id": "seed.proj.s",
        "resource_type": "seed",
        "original_file_path": "seeds/s.csv",
        "fqn": ["proj", "s"],
        "unrendered_config": {},
        "config": {},
        "columns": {},
        "description": "",
        "depends_on": {"nodes": [], "macros": []},
        "checksum": {"name": "sha256", "checksum": cs},
        "raw_code": "",
    }
    assert modified(_manifest([seed("aaa")]), _manifest([seed("bbb")])) == {"seed.proj.s": ["body"]}


# ── recursive macro closure (macro_sql only) ─────────────────────────────────────────────────────
def test_changed_macro_flags_dependent_model() -> None:
    macros_old = {"macro.proj.m": {"unique_id": "macro.proj.m", "macro_sql": "old", "depends_on": {"macros": []}}}
    macros_new = {"macro.proj.m": {"unique_id": "macro.proj.m", "macro_sql": "new", "depends_on": {"macros": []}}}
    node = _model("model.proj.a", depends_on={"nodes": [], "macros": ["macro.proj.m"]})
    base = _manifest([node], macros=macros_old)
    cur = _manifest([node], macros=macros_new)
    assert modified(base, cur) == {"model.proj.a": ["macros"]}


def test_macro_closure_is_recursive() -> None:
    # model -> macro a -> macro b ; only b's SQL changes. The closure must reach b through a.
    a = {"unique_id": "macro.proj.a", "macro_sql": "stable", "depends_on": {"macros": ["macro.proj.b"]}}
    b_old = {"unique_id": "macro.proj.b", "macro_sql": "old", "depends_on": {"macros": []}}
    b_new = {"unique_id": "macro.proj.b", "macro_sql": "new", "depends_on": {"macros": []}}
    node = _model("model.proj.a", depends_on={"nodes": [], "macros": ["macro.proj.a"]})
    base = _manifest([node], macros={"macro.proj.a": a, "macro.proj.b": b_old})
    cur = _manifest([node], macros={"macro.proj.a": a, "macro.proj.b": b_new})
    assert modified(base, cur) == {"model.proj.a": ["macros"]}


def test_none_macro_id_raises() -> None:
    node = _model("model.proj.a", depends_on={"nodes": [], "macros": [None]})
    with pytest.raises(ValueError, match="unresolved"):
        modified(_manifest([node]), _manifest([node]))


# ── M+ : descendants of a change ─────────────────────────────────────────────────────────────────
def test_modified_plus_adds_downstream_descendants() -> None:
    a = _model("model.proj.a", raw_code="select 2")  # changed
    a_base = _model("model.proj.a")
    b = _model("model.proj.b", depends_on={"nodes": ["model.proj.a"], "macros": []})  # child of a, unchanged
    base = _manifest([a_base, b])
    cur = _manifest([a, b])
    assert modified(base, cur) == {"model.proj.a": ["body"]}  # direct M: only a
    plus = modified_plus(base, cur)
    assert plus == {"model.proj.a": ["body"], "model.proj.b": ["downstream"]}  # M+: a and its child b


def test_model_path_projections() -> None:
    a = _model("model.proj.a", raw_code="select 2")
    b = _model("model.proj.b", depends_on={"nodes": ["model.proj.a"], "macros": []})
    base = _manifest([_model("model.proj.a"), b])
    cur = _manifest([a, b])
    assert modified_model_paths(base, cur, plus=False) == {"models/a.sql"}
    assert modified_model_paths(base, cur, plus=True) == {"models/a.sql", "models/b.sql"}
    assert modified_model_reasons(base, cur, plus=True) == {"models/a.sql": ["body"], "models/b.sql": ["downstream"]}


# ── the dataclass surface (State / StateModified) ────────────────────────────────────────────────
def test_statemodified_dataclass_api() -> None:
    a = _model("model.proj.a", raw_code="select 2")
    b = _model("model.proj.b", depends_on={"nodes": ["model.proj.a"], "macros": []})
    sm = StateModified.compare(
        State.from_manifest(_manifest([_model("model.proj.a"), b])),
        State.from_manifest(_manifest([a, b])),
    )
    assert sm.direct == {"model.proj.a": ["body"]}  # M
    assert sm.plus == {"model.proj.a": ["body"], "model.proj.b": ["downstream"]}  # M+
    assert sm.verdict(plus=False) == sm.direct
    assert sm.model_paths(plus=True) == {"models/a.sql", "models/b.sql"}
    assert sm.model_reasons(plus=False) == {"models/a.sql": ["body"]}
