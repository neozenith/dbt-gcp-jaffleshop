"""Tests for the deterministic taxonomy detectors — pure logic over hand-built manifest data.

No warehouse, no LLM: a constructed manifest dict (the shape dbt writes) exercises the parser,
the freshness-structure trap, each detector, and the registry-vs-catalogue invariant.
"""

from adaf.commands import taxonomy as tax_cmd
from adaf.rules import all_rules
from adaf.taxonomy import (
    DETECTORS,
    MISSING,
    PRESENT,
    NodeFacts,
    AttachedTest,
    _detect_en01,
    _detect_en03,
    _detect_md01,
    _detect_md02,
    _detect_tmau01,
    _source_has_freshness,
    node_facts_from_manifest,
)


def _model(name, layer, columns, contract=False, tests=None) -> NodeFacts:
    return NodeFacts(
        unique_id=f"model.p.{name}", name=name, resource_type="model",
        original_file_path=f"models/{layer}/{name}.sql", layer=layer, columns=columns,
        contract_enforced=contract, has_freshness=False, tests=tests or [],
    )


# ─── freshness-structure trap ────────────────────────────────────────────────


def test_source_freshness_empty_structure_is_not_a_sla() -> None:
    # dbt always writes this empty shape when no freshness is configured.
    node = {"loaded_at_field": "ts", "freshness": {"warn_after": {"count": None, "period": None},
                                                   "error_after": {"count": None, "period": None}}}
    assert _source_has_freshness(node) is False


def test_source_freshness_real_sla_is_detected() -> None:
    node = {"loaded_at_field": "ts", "freshness": {"warn_after": {"count": 24, "period": "hour"},
                                                   "error_after": {"count": None}}}
    assert _source_has_freshness(node) is True


def test_source_freshness_requires_loaded_at_field() -> None:
    node = {"loaded_at_field": None, "freshness": {"warn_after": {"count": 24, "period": "hour"}}}
    assert _source_has_freshness(node) is False


# ─── detectors ───────────────────────────────────────────────────────────────


def test_md01_present_with_grain_test_and_missing_without() -> None:
    with_grain = _model("orders", "marts", ["order_id"], tests=[AttachedTest("unique_combination_of_columns", "dbt_utils", None)])
    without = _model("products", "marts", ["product_id"])
    assert _detect_md01(with_grain)[0] == PRESENT
    assert _detect_md01(without)[0] == MISSING


def test_tmau01_only_applies_to_sources() -> None:
    model = _model("orders", "marts", ["order_id"])
    assert _detect_tmau01(model) is None  # not a source → rule role doesn't apply
    src = NodeFacts("source.p.raw.x", "x", "source", "models/staging/__sources.yml", "", [], False, has_freshness=False)
    assert _detect_tmau01(src)[0] == MISSING


def test_md02_only_flags_marts_without_a_contract() -> None:
    assert _detect_md02(_model("stg_orders", "staging", ["order_id"])) is None  # staging is out of scope
    assert _detect_md02(_model("orders", "marts", ["order_id"]))[0] == MISSING
    assert _detect_md02(_model("orders", "marts", ["order_id"], contract=True))[0] == PRESENT


def test_en01_pk_needs_unique_and_not_null() -> None:
    good = _model("customers", "marts", ["customer_id"],
                  tests=[AttachedTest("unique", None, "customer_id"), AttachedTest("not_null", None, "customer_id")])
    bad = _model("customers", "marts", ["customer_id"], tests=[AttachedTest("unique", None, "customer_id")])
    assert _detect_en01(good)[0] == PRESENT
    assert _detect_en01(bad)[0] == MISSING and "not_null" in _detect_en01(bad)[1]


def test_en03_flags_fk_without_relationships() -> None:
    n = _model("order_items", "marts", ["order_item_id", "order_id"],
               tests=[AttachedTest("unique", None, "order_item_id")])  # order_id (FK) has no relationships test
    status, detail = _detect_en03(n)
    assert status == MISSING and "order_id" in detail


# ─── manifest parsing + registry invariant ───────────────────────────────────


def test_node_facts_from_manifest_attributes_tests() -> None:
    manifest = {
        "nodes": {
            "model.p.orders": {"resource_type": "model", "name": "orders",
                               "original_file_path": "models/marts/orders.sql",
                               "columns": {"order_id": {}}, "contract": {"enforced": True}},
            "test.p.u": {"resource_type": "test", "column_name": "order_id",
                         "test_metadata": {"name": "unique", "kwargs": {"column_name": "order_id"}},
                         "depends_on": {"nodes": ["model.p.orders"]}},
        },
        "sources": {
            "source.p.raw.raw_orders": {"resource_type": "source", "name": "raw_orders",
                                        "original_file_path": "models/staging/__sources.yml",
                                        "columns": {}, "loaded_at_field": None, "freshness": {}},
        },
    }
    facts = {f.name: f for f in node_facts_from_manifest(manifest)}
    assert facts["orders"].contract_enforced is True
    assert facts["orders"].layer == "marts"
    assert "unique" in facts["orders"].test_names()
    assert facts["raw_orders"].has_freshness is False


def test_every_deterministic_rule_has_a_detector() -> None:
    deterministic = {r["code"] for r in all_rules() if r["detection"] == "deterministic"}
    assert deterministic <= set(DETECTORS), f"deterministic rules without a detector: {deterministic - set(DETECTORS)}"


def test_report_blocker_fails_warning_does_not() -> None:
    blocker = tax_cmd.TaxonomyFinding("products", "model", "MD-01", "deterministic", "blocker", MISSING, "x")
    warning = tax_cmd.TaxonomyFinding("orders", "model", "MD-02", "hybrid", "warning", MISSING, "x")
    assert tax_cmd.TaxonomyReport("s", [blocker]).ok is False
    assert tax_cmd.TaxonomyReport("s", [warning]).ok is True
    assert tax_cmd.TaxonomyReport("s", [warning], strict=True).ok is False
