"""Unit tests for the sdag boundary-obligation lint — pure (synthetic manifest, no dbt/warehouse).

Exercises the manifest artifact-detection (:class:`Artifacts`) and per-node rule evaluation
(:func:`evaluate_node`) against a hand-built manifest dict. No `dbt ls` / `dbt parse` is invoked.
"""

# Standard Library
from typing import Any

# Third Party
import pytest
from ruamel.yaml import YAML

# First Party
from adaf.commands.sdaglint import (
    Artifacts,
    Violation,
    _print_product_report,
    _print_violation_summary,
    evaluate_node,
)
from adaf.dbt.graph import BOTH, INBOUND, INNER, OUTBOUND, Graph
from adaf.suppression import Suppressions, load_suppressions

_yaml = YAML()


def _manifest() -> dict[str, Any]:
    """A product {src_in -> stg -> fct} feeding an external downstream model.

        source.p.src_in --> model.p.stg --> model.p.fct --> model.p.downstream(external)

    Members: src_in, stg, fct. ``Graph.classify`` labels ONLY models (sources/exposures are edges):
      - stg = inbound  (reads an external source -> entry point; src_in is NOT a subject)
      - fct = outbound (feeds an external model + exposure -> exit point)

    The ``evaluate_node`` tests below pass explicit boundary labels (independent of classify) so
    each rule can be exercised. Artifacts planted on the manifest:
      - fct has an enforced contract + an exposure, but NO semantic model -> MD-12 fires.
      - the inbound model stg reads src_in, which has NO freshness and NO volume test -> TM-AU-01 + MD-07 fire.
    """
    return {
        "nodes": {
            "model.p.stg": {
                "resource_type": "model",
                "name": "stg",
                "original_file_path": "models/staging/stg.sql",
            },
            "model.p.fct": {
                "resource_type": "model",
                "name": "fct",
                "original_file_path": "models/marts/fct.sql",
                "config": {"contract": {"enforced": True}},
            },
            "model.p.downstream": {
                "resource_type": "model",
                "name": "downstream",
                "original_file_path": "models/marts/downstream.sql",
            },
            "test.p.exp_test": {
                "resource_type": "test",
                "name": "some_other_test",
                "depends_on": {"nodes": ["model.p.fct"]},
            },
        },
        "sources": {
            "source.p.src_in": {
                "resource_type": "source",
                "name": "src_in",
                "original_file_path": "models/staging/_sources.yml",
                # no `freshness` key -> not fresh
            },
        },
        "exposures": {
            "exposure.p.dashboard": {"depends_on": {"nodes": ["model.p.fct"]}},
        },
        "semantic_models": {},  # none -> fct has no semantic model
        "parent_map": {
            "source.p.src_in": [],
            "model.p.stg": ["source.p.src_in"],
            "model.p.fct": ["model.p.stg"],
            "model.p.downstream": ["model.p.fct"],
        },
    }


MEMBERS = {"source.p.src_in", "model.p.stg", "model.p.fct"}


# ─── Artifacts detection ──────────────────────────────────────────────────────


def test_artifacts_contract_detection() -> None:
    art = Artifacts.from_manifest(_manifest())
    assert "model.p.fct" in art.contracts
    assert "model.p.stg" not in art.contracts


def test_artifacts_exposure_and_semantic() -> None:
    art = Artifacts.from_manifest(_manifest())
    assert "model.p.fct" in art.exposure_deps
    assert art.semantic_deps == frozenset()  # no semantic models defined


def test_artifacts_freshness_present_vs_absent() -> None:
    data = _manifest()
    art = Artifacts.from_manifest(data)
    assert "source.p.src_in" not in art.fresh_sources  # no freshness key
    # Add a freshness policy -> now detected.
    data["sources"]["source.p.src_in"]["freshness"] = {"warn_after": {"count": 24, "period": "hour"}}
    assert "source.p.src_in" in Artifacts.from_manifest(data).fresh_sources


def test_volume_anomaly_heuristic_namespace_and_name() -> None:
    data = _manifest()
    data["nodes"]["test.p.vol"] = {
        "resource_type": "test",
        "name": "elementary_volume_anomalies_src_in",
        "depends_on": {"nodes": ["source.p.src_in"]},
        "test_metadata": {"namespace": "elementary", "name": "volume_anomalies"},
    }
    art = Artifacts.from_manifest(data)
    assert "source.p.src_in" in art.volume_targets


def test_volume_anomaly_heuristic_lenient_name_only() -> None:
    data = _manifest()
    # No test_metadata.namespace, but the unique_id/name carries the Elementary signature.
    data["nodes"]["test.p.vol2"] = {
        "resource_type": "test",
        "unique_id": "test.p.volume_anomalies_abc",
        "name": "volume_anomalies_abc",
        "depends_on": {"nodes": ["source.p.src_in"]},
    }
    assert "source.p.src_in" in Artifacts.from_manifest(data).volume_targets


def test_node_info_resolves_resource_type_and_path() -> None:
    art = Artifacts.from_manifest(_manifest())
    assert art.nodes["model.p.fct"].resource_type == "model"
    assert art.nodes["model.p.fct"].original_file_path == "models/marts/fct.sql"
    assert art.nodes["source.p.src_in"].resource_type == "source"


# ─── classification + rule evaluation ─────────────────────────────────────────


def test_classification_of_members() -> None:
    labels = Graph.from_dict(_manifest()).classify(MEMBERS)
    assert labels == {
        "model.p.stg": INBOUND,  # reads an external source -> entry point (owes freshness/volume)
        "model.p.fct": OUTBOUND,  # feeds an external model + exposure -> exit point
    }
    assert "source.p.src_in" not in labels  # a source is the inbound edge, never a boundary subject


def test_outbound_model_missing_semantic_fires_only_semantic() -> None:
    art = Artifacts.from_manifest(_manifest())
    # fct has contract + exposure but no semantic model.
    violations = evaluate_node("model.p.fct", OUTBOUND, art, Suppressions())
    rule_ids = {v.rule_id for v in violations}
    assert rule_ids == {"MD-12"}


def test_outbound_model_missing_all_three() -> None:
    art = Artifacts.from_manifest(_manifest())
    # stg as a hypothetical outbound node: no contract, no exposure, no semantic.
    violations = evaluate_node("model.p.stg", OUTBOUND, art, Suppressions())
    assert {v.rule_id for v in violations} == {"MD-02", "MD-11", "MD-12"}


def test_inbound_model_missing_freshness_and_volume() -> None:
    art = Artifacts.from_manifest(_manifest())
    # The inbound MODEL owns the freshness/volume obligations via the source it reads (src_in has neither).
    violations = evaluate_node("model.p.stg", INBOUND, art, Suppressions())
    assert {v.rule_id for v in violations} == {"TM-AU-01", "MD-07"}


def test_source_is_never_a_boundary_subject() -> None:
    art = Artifacts.from_manifest(_manifest())
    # Sources are edges, not subjects: the inbound rules are now model-only, so a source owes nothing.
    assert evaluate_node("source.p.src_in", INBOUND, art, Suppressions()) == []
    assert evaluate_node("source.p.src_in", BOTH, art, Suppressions()) == []


def test_fresh_source_satisfies_inbound_model() -> None:
    data = _manifest()
    data["sources"]["source.p.src_in"]["freshness"] = {"warn_after": {"count": 1, "period": "day"}}
    art = Artifacts.from_manifest(data)
    # stg now reads a FRESH source -> TM-AU-01 satisfied; only MD-07 (no volume test) remains.
    assert {v.rule_id for v in evaluate_node("model.p.stg", INBOUND, art, Suppressions())} == {"MD-07"}


def test_inner_node_has_no_obligations() -> None:
    art = Artifacts.from_manifest(_manifest())
    assert evaluate_node("model.p.stg", INNER, art, Suppressions()) == []


def test_both_model_gets_outbound_and_inbound_rules() -> None:
    art = Artifacts.from_manifest(_manifest())
    # A model classified `both`: outbound trio + the inbound pair (its source is neither fresh nor volume-tested).
    violations = evaluate_node("model.p.stg", BOTH, art, Suppressions())
    assert {v.rule_id for v in violations} == {"MD-02", "MD-11", "MD-12", "TM-AU-01", "MD-07"}


def test_suppressed_violation_not_reported(tmp_path: Any) -> None:
    art = Artifacts.from_manifest(_manifest())
    cfg = tmp_path / ".adaf.yml"
    # The inbound subject is now the MODEL, so suppression matches on the model's path.
    cfg.write_text(
        "suppress:\n  - rule: TM-AU-01\n    paths: ['models/staging/stg.sql']\n",
        encoding="utf-8",
    )
    sup = load_suppressions(cfg)
    violations = evaluate_node("model.p.stg", INBOUND, art, sup)
    # TM-AU-01 suppressed for that path; MD-07 still fires.
    assert {v.rule_id for v in violations} == {"MD-07"}


def test_violation_carries_label_and_path() -> None:
    art = Artifacts.from_manifest(_manifest())
    [v] = evaluate_node("model.p.fct", OUTBOUND, art, Suppressions())
    assert isinstance(v, Violation)
    assert v.label == OUTBOUND
    assert v.file_path == "models/marts/fct.sql"


def test_violation_carries_guidance_and_url() -> None:
    art = Artifacts.from_manifest(_manifest())
    # fct is missing only its semantic model -> MD-12, which links to the dbt semantic-models docs.
    [v] = evaluate_node("model.p.fct", OUTBOUND, art, Suppressions())
    assert v.rule_id == "MD-12"
    assert v.guidance  # an actionable sentence, not empty
    assert v.url == "https://docs.getdbt.com/docs/build/semantic-models"


def test_all_rules_have_guidance_and_url() -> None:
    # Every emitted violation must carry non-empty guidance + a doc URL.
    art = Artifacts.from_manifest(_manifest())
    outbound = evaluate_node("model.p.stg", OUTBOUND, art, Suppressions())
    inbound = evaluate_node("model.p.stg", INBOUND, art, Suppressions())  # inbound subject is the model now
    for v in [*outbound, *inbound]:
        assert v.guidance, f"{v.rule_id} has no guidance"
        assert v.url.startswith("https://"), f"{v.rule_id} has no doc url"


# ─── _print_product_report: the shared-report rendering (capsys, no mocks) ─────


def _violations() -> list[Violation]:
    """Two violations on one model node, exercising grouping + rule-ID ordering."""
    return [
        Violation(
            unique_id="model.p.fct",
            label=OUTBOUND,
            rule_id="MD-12",
            description="missing semantic model",
            file_path="models/marts/fct.sql",
            guidance="Define a semantic model on top of this model.",
            url="https://docs.getdbt.com/docs/build/semantic-models",
        ),
        Violation(
            unique_id="model.p.fct",
            label=OUTBOUND,
            rule_id="MD-02",
            description="missing enforced data contract",
            file_path="models/marts/fct.sql",
            guidance="Add `contract: {enforced: true}` to the model's config.",
            url="https://docs.getdbt.com/docs/collaborate/govern/model-contracts",
        ),
    ]


def test_print_product_report_header_on_stderr_findings_on_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    _print_product_report("demand", _violations(), color=False)
    captured = capsys.readouterr()

    # The sqlfluff-style group header is a human delimiter -> stderr, NOT the pipeable stream.
    assert "== [product: demand] FAIL" in captured.err
    assert "== [product: demand] FAIL" not in captured.out

    # Findings render through report.render_finding on stdout: path: [error] CODE message.
    out_lines = captured.out.splitlines()
    finding_lines = [ln for ln in out_lines if ln.startswith("models/")]
    assert finding_lines == [
        "models/marts/fct.sql: [error] MD-02 missing enforced data contract",
        "models/marts/fct.sql: [error] MD-12 missing semantic model",  # sorted by rule_id
    ]


def test_print_product_report_omits_inline_guidance(capsys: pytest.CaptureFixture[str]) -> None:
    # The findings listing is now bare — guidance/see: URLs are aggregated by _print_violation_summary,
    # not repeated under every finding.
    _print_product_report("demand", _violations(), color=False)
    captured = capsys.readouterr()
    assert "Add `contract: {enforced: true}`" not in captured.out
    assert "see:" not in captured.out


def test_violation_summary_aggregates_counts_then_advice_once(capsys: pytest.CaptureFixture[str]) -> None:
    # Two MD-02 violations on different nodes must yield ONE MD-02 advice line and a "× 2" tally —
    # the de-duplication the user asked for. MD-12 appears once (× 1).
    violations = [
        *_violations(),  # one MD-12 + one MD-02 on model.p.fct
        Violation(
            unique_id="model.p.dim",
            label=OUTBOUND,
            rule_id="MD-02",
            description="missing enforced data contract",
            file_path="models/marts/dim.sql",
            guidance="Add `contract: {enforced: true}` to the model's config.",
            url="https://docs.getdbt.com/docs/collaborate/govern/model-contracts",
        ),
    ]
    _print_violation_summary(violations, color=False)
    err = capsys.readouterr().err

    # Aggregated counts block, then the advice block — both on stderr (summary, not findings).
    assert "violations by rule:" in err
    assert "MD-02 × 2  missing enforced data contract" in err
    assert "MD-12 × 1  missing semantic model" in err
    assert "how to fix:" in err

    # Each rule's guidance + see: URL appears EXACTLY ONCE despite MD-02 tripping twice.
    assert err.count("Add `contract: {enforced: true}` to the model's config.") == 1
    assert err.count("see: https://docs.getdbt.com/docs/collaborate/govern/model-contracts") == 1
    assert err.count("Define a semantic model on top of this model.") == 1


def test_print_product_report_no_ansi_when_color_off(capsys: pytest.CaptureFixture[str]) -> None:
    _print_product_report("demand", _violations(), color=False)
    captured = capsys.readouterr()
    assert "\x1b[" not in captured.out
    assert "\x1b[" not in captured.err


def test_print_product_report_color_emits_ansi(capsys: pytest.CaptureFixture[str]) -> None:
    _print_product_report("demand", _violations(), color=True)
    captured = capsys.readouterr()
    assert "\x1b[31m" in captured.err  # FAIL header coloured red (error severity)
    assert "\x1b[31m" in captured.out  # [error] tag coloured red
    assert "\x1b[2m" in captured.out  # path + notes dimmed


def test_print_product_report_falls_back_to_unique_id_when_no_path(capsys: pytest.CaptureFixture[str]) -> None:
    v = Violation(
        unique_id="source.p.src_in",
        label=INBOUND,
        rule_id="TM-AU-01",
        description="missing source freshness",
        file_path="",  # no original_file_path in the manifest
        guidance="Add a `freshness:` block.",
        url="https://docs.getdbt.com/reference/resource-properties/freshness",
    )
    _print_product_report("demand", [v], color=False)
    out = capsys.readouterr().out
    assert "source.p.src_in: [error] TM-AU-01 missing source freshness" in out
