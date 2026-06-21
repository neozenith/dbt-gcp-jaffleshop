"""Unit tests for the per-selector compliance enrichment (``adaf.annotations``).

Builds a real :class:`~adaf.dbt.manifest_view.ManifestView` from a hand-built manifest dict (mirrors
``tests/test_sdaglint.py``) and asserts the enriched cache structure: the product-level rollup
counts and the per boundary-node pass/fail/suppressed rule entries. No mocks, no dbt — the same
``Artifacts`` / ``evaluate_node`` the lint gate uses are exercised end-to-end through
``compute_compliance``, and ``enrich_selector_cache`` is driven against a real on-disk cache file.
"""

# Standard Library
import json
from pathlib import Path
from typing import Any

# First Party
from adaf import annotations
from adaf.dbt import cache
from adaf.dbt.manifest_view import ManifestView
from adaf.suppression import Suppressions

# An empty suppression set (no adaf.yml under a nonexistent root → never suppresses).
_NO_SUP = Suppressions(Path("/nonexistent"))


def _manifest() -> dict[str, Any]:
    """A product {src_in -> stg -> fct} feeding an external downstream model.

    Over MEMBERS, ``Graph.classify`` yields: src_in=inbound, stg=internal, fct=outbound.
    Planted artifacts: fct has a contract + an exposure but NO semantic model (MD-12 fails);
    src_in has NO freshness and NO volume-anomaly test (TM-AU-01 + MD-07 fail).
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
        },
        "sources": {
            "source.p.src_in": {
                "resource_type": "source",
                "name": "src_in",
                "original_file_path": "models/staging/_sources.yml",
            },
        },
        "exposures": {
            "exposure.p.dashboard": {"depends_on": {"nodes": ["model.p.fct"]}},
        },
        "semantic_models": {},
        "parent_map": {
            "source.p.src_in": [],
            "model.p.stg": ["source.p.src_in"],
            "model.p.fct": ["model.p.stg"],
            "model.p.downstream": ["model.p.fct"],
        },
    }


MEMBERS = {"source.p.src_in", "model.p.stg", "model.p.fct"}


def _view() -> ManifestView:
    return ManifestView.from_dict(_manifest())


def _rules_by_id(node_annotation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["rule_id"]: entry for entry in node_annotation["rules"]}


# ─── compute_compliance: per-node annotations ─────────────────────────────────


def test_inner_node_is_omitted() -> None:
    result = annotations.compute_compliance(_view(), MEMBERS, _NO_SUP)
    # stg is interior to the product -> no boundary obligations -> not annotated.
    assert "model.p.stg" not in result["annotations"]
    assert set(result["annotations"]) == {"source.p.src_in", "model.p.fct"}


def test_outbound_model_rule_statuses() -> None:
    result = annotations.compute_compliance(_view(), MEMBERS, _NO_SUP)
    fct = result["annotations"]["model.p.fct"]
    assert fct["boundary"] == "outbound"
    rules = _rules_by_id(fct)
    # fct has a contract (MD-02 pass) + exposure (MD-11 pass) but no semantic model (MD-12 fail).
    assert rules["MD-02"]["status"] == "pass"
    assert rules["MD-11"]["status"] == "pass"
    assert rules["MD-12"]["status"] == "fail"
    assert rules["MD-12"]["message"] == "missing semantic model"
    assert rules["MD-12"]["guidance"]
    assert rules["MD-12"]["url"].startswith("https://")


def test_inbound_source_rule_statuses() -> None:
    result = annotations.compute_compliance(_view(), MEMBERS, _NO_SUP)
    src = result["annotations"]["source.p.src_in"]
    assert src["boundary"] == "inbound"
    rules = _rules_by_id(src)
    # No freshness, no volume-anomaly test -> both inbound obligations fail.
    assert rules["TM-AU-01"]["status"] == "fail"
    assert rules["MD-07"]["status"] == "fail"


# ─── compute_compliance: rollup ───────────────────────────────────────────────


def test_rollup_counts_match_node_statuses() -> None:
    result = annotations.compute_compliance(_view(), MEMBERS, _NO_SUP)
    roll = result["compliance"]
    assert roll["boundary_nodes"] == 2
    assert roll["total"] == 5
    assert roll["passed"] == 2
    assert roll["failed"] == 3
    assert roll["suppressed"] == 0
    assert roll["failed_nodes"] == 2
    # compliant = total - failed = 2/5 = 40.0%
    assert roll["compliance_pct"] == 40.0


def test_fully_compliant_product_is_100_pct() -> None:
    data = _manifest()
    # Satisfy every obligation: freshness + volume test on the source, semantic model on fct.
    data["sources"]["source.p.src_in"]["freshness"] = {"warn_after": {"count": 1, "period": "day"}}
    data["nodes"]["test.p.vol"] = {
        "resource_type": "test",
        "name": "volume_anomalies_src_in",
        "depends_on": {"nodes": ["source.p.src_in"]},
        "test_metadata": {"namespace": "elementary", "name": "volume_anomalies"},
    }
    data["semantic_models"]["semantic_model.p.fct"] = {"depends_on": {"nodes": ["model.p.fct"]}}
    result = annotations.compute_compliance(ManifestView.from_dict(data), MEMBERS, _NO_SUP)
    roll = result["compliance"]
    assert roll["failed"] == 0
    assert roll["compliance_pct"] == 100.0


# ─── suppressions honoured the same way as sdag check ─────────────────────────


def test_suppressed_obligation_does_not_fail(tmp_path: Path) -> None:
    (tmp_path / "adaf.yml").write_text(
        "disable:\n  - rules: [TM-AU-01]\n    paths: ['models/staging/_sources.yml']\n",
        encoding="utf-8",
    )
    sup = Suppressions.load(tmp_path)
    result = annotations.compute_compliance(_view(), MEMBERS, sup)
    rules = _rules_by_id(result["annotations"]["source.p.src_in"])
    # TM-AU-01 is excused (suppressed, not failed); MD-07 still fails.
    assert rules["TM-AU-01"]["status"] == "suppressed"
    assert rules["MD-07"]["status"] == "fail"
    roll = result["compliance"]
    assert roll["suppressed"] == 1
    assert roll["failed"] == 2  # MD-07 + MD-12
    # A suppressed obligation counts as compliant: compliant = 5 - 2 = 3 -> 60.0%
    assert roll["compliance_pct"] == 60.0


# ─── enrich_selector_cache: additive merge into the real cache file ───────────


def test_enrich_is_additive_and_preserves_existing_cache(tmp_path: Path) -> None:
    manifest = tmp_path / "target" / "manifest.json"
    selectors = tmp_path / "selectors.yml"
    for p in (manifest, selectors):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    # The generate flow writes membership + boundaries first; enrich must not clobber them.
    entry = cache.SelectorCacheEntry(
        members=MEMBERS,
        boundaries={"source.p.src_in": "inbound", "model.p.stg": "internal", "model.p.fct": "outbound"},
    )
    cache.save_selector(tmp_path, manifest, selectors, "demand", entry)

    annotations.enrich_selector_cache(tmp_path, "demand", _view(), MEMBERS, _NO_SUP)

    blob = json.loads(cache.selector_cache_path(tmp_path, "demand").read_text(encoding="utf-8"))
    assert blob["selector"] == "demand"
    assert set(blob["members"]) == MEMBERS
    assert blob["boundaries"]["model.p.fct"] == "outbound"
    assert "fingerprint" in blob
    assert blob["compliance"]["total"] == 5
    assert blob["annotations"]["model.p.fct"]["boundary"] == "outbound"
    loaded = cache.load_selector(tmp_path, manifest, selectors, "demand")
    assert loaded is not None
    assert loaded.members == MEMBERS


def test_enrich_missing_cache_file_raises(tmp_path: Path) -> None:
    try:
        annotations.enrich_selector_cache(tmp_path, "absent", _view(), MEMBERS, _NO_SUP)
    except FileNotFoundError as exc:
        assert "absent" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError for a missing cache file")
