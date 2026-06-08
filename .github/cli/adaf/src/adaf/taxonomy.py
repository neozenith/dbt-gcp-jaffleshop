"""Deterministic taxonomy detectors — the programmatic half of the testing taxonomy.

Some catalogue rules can be checked by a SCRIPT reading ``manifest.json`` (no LLM, no
warehouse): does a model carry a grain test? does a source declare freshness? is a mart
contracted? This module is the pure engine for those — it distils each model/source node
into :class:`NodeFacts` and runs the registered detectors over it.

Two detector tiers, mirroring the catalogue's ``detection`` field:

* ``deterministic`` rules (MD-01, TM-AU-01) — the trigger AND the artifact are statically
  decidable, so a missing artifact is a hard **blocker**.
* ``hybrid`` rules (MD-02, EN-01, EN-03) — the artifact is statically detectable but whether
  the rule APPLIES needs judgement, so a structural-precondition heuristic flags a likely gap
  as an advisory **warning** (suppressible; the LLM ``review`` adjudicates the rest).

Every detector returns a status of present / missing / not_applicable. ``missing`` on a
deterministic rule fails the gate; ``missing`` on a hybrid rule is advisory. The registry is
cross-checked against the catalogue: every ``deterministic``-tagged rule MUST have a detector.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# status values
PRESENT = "present"
MISSING = "missing"
NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class AttachedTest:
    """One test attached to a data node, distilled from a manifest test node."""

    name: str  # generic test name: unique, not_null, relationships, unique_combination_of_columns, ...
    namespace: str | None  # dbt_utils / dbt_expectations / None (core or singular)
    column: str | None  # the column it targets, when column-level


@dataclass
class NodeFacts:
    """Everything a detector needs about one model/source node — pure data, no manifest coupling."""

    unique_id: str
    name: str
    resource_type: str  # "model" | "source"
    original_file_path: str
    layer: str  # the first dir under models/ (e.g. "staging", "marts"); "" for sources
    columns: list[str]
    contract_enforced: bool
    has_freshness: bool  # source declared a freshness block
    tests: list[AttachedTest] = field(default_factory=list)

    def test_names(self) -> set[str]:
        return {t.name for t in self.tests}

    def tests_on(self, column: str) -> set[str]:
        return {t.name for t in self.tests if t.column and t.column.lower() == column.lower()}

    def id_columns(self) -> list[str]:
        """Columns that look like keys (``*_id`` / ``*_uuid`` / bare ``id``)."""
        return [c for c in self.columns if c.lower().endswith(("_id", "_uuid")) or c.lower() == "id"]

    def pk_column(self) -> str | None:
        """The model's likely primary key: ``<name>_id`` (singularised), else a sole ``*_id`` column."""
        ids = self.id_columns()
        singular = self.name[:-1] if self.name.endswith("s") else self.name
        for cand in (f"{self.name}_id", f"{singular}_id"):
            match = next((c for c in ids if c.lower() == cand.lower()), None)
            if match:
                return match
        return ids[0] if len(ids) == 1 else None


# ─── manifest → NodeFacts ────────────────────────────────────────────────────


def _layer_of(original_file_path: str) -> str:
    """The first directory segment under ``models/`` (the project layer), or '' if not under models/."""
    parts = Path(original_file_path).parts
    if "models" in parts:
        i = parts.index("models")
        if i + 2 < len(parts):  # models/<layer>/<file>
            return parts[i + 1]
    return ""


def _source_has_freshness(node: dict) -> bool:
    """A REAL freshness SLA, not just dbt's always-present empty structure.

    dbt writes a ``freshness`` object on every source even when none is configured
    (``warn_after``/``error_after`` with null counts), so a truthiness check false-positives.
    A genuine SLA needs a ``loaded_at_field`` AND at least one of warn/error with a count set.
    """
    if not node.get("loaded_at_field"):
        return False
    fr = node.get("freshness") or {}
    return any((fr.get(k) or {}).get("count") is not None for k in ("warn_after", "error_after"))


def _test_fact(node: dict) -> AttachedTest | None:
    """Distil a manifest test node into an AttachedTest (None for singular/data tests with no metadata)."""
    meta = node.get("test_metadata")
    if not meta:
        return None  # singular (data) test — no generic name to key on
    kwargs = meta.get("kwargs") or {}
    column = node.get("column_name") or kwargs.get("column_name")
    return AttachedTest(name=meta.get("name", ""), namespace=meta.get("namespace"), column=column)


def node_facts_from_manifest(data: dict) -> list[NodeFacts]:
    """Build NodeFacts for every model and source in a dbt manifest dict (the same shape dbt writes)."""
    nodes = data.get("nodes") or {}
    sources = data.get("sources") or {}
    facts: dict[str, NodeFacts] = {}

    for uid, node in nodes.items():
        if node.get("resource_type") != "model":
            continue
        ofp = node.get("original_file_path", "")
        facts[uid] = NodeFacts(
            unique_id=uid,
            name=node.get("name", ""),
            resource_type="model",
            original_file_path=ofp,
            layer=_layer_of(ofp),
            columns=list((node.get("columns") or {}).keys()),
            contract_enforced=bool((node.get("contract") or {}).get("enforced")),
            has_freshness=False,
        )
    for uid, node in sources.items():
        facts[uid] = NodeFacts(
            unique_id=uid,
            name=node.get("name", ""),
            resource_type="source",
            original_file_path=node.get("original_file_path", ""),
            layer="",
            columns=list((node.get("columns") or {}).keys()),
            contract_enforced=False,
            has_freshness=_source_has_freshness(node),
        )

    # Attribute each generic test to the data node(s) it depends on.
    for node in nodes.values():
        if node.get("resource_type") != "test":
            continue
        tf = _test_fact(node)
        if tf is None:
            continue
        for dep in (node.get("depends_on") or {}).get("nodes", []):
            if dep in facts:
                facts[dep].tests.append(tf)
    return list(facts.values())


# ─── detectors (pure: NodeFacts -> (status, detail) | None when the rule's role doesn't apply) ──

_GRAIN_TESTS = {"unique_combination_of_columns", "unique"}


def _detect_md01(n: NodeFacts) -> tuple[str, str] | None:
    """MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test."""
    if n.resource_type != "model":
        return None
    if n.test_names() & _GRAIN_TESTS:
        return PRESENT, "has a uniqueness/grain test"
    return MISSING, "no grain test — add unique_combination_of_columns (or unique) naming the grain"


def _detect_tmau01(n: NodeFacts) -> tuple[str, str] | None:
    """TM-AU-01 freshness: every SOURCE must declare a freshness block."""
    if n.resource_type != "source":
        return None
    if n.has_freshness:
        return PRESENT, "source declares a freshness SLA"
    return MISSING, "source has no freshness: block — add loaded_at_field + warn_after/error_after"


def _detect_md02(n: NodeFacts) -> tuple[str, str] | None:
    """MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/."""
    if n.resource_type != "model" or n.layer != "marts":
        return None
    if n.contract_enforced:
        return PRESENT, "contract.enforced: true"
    return MISSING, "mart has no enforced contract — add contract: {enforced: true} to pin its shape"


def _detect_en01(n: NodeFacts) -> tuple[str, str] | None:
    """EN-01 unique-key (hybrid): the model's PK column should have unique + not_null."""
    if n.resource_type != "model":
        return None
    pk = n.pk_column()
    if pk is None:
        return None  # no identifiable PK column — leave to the LLM
    on = n.tests_on(pk)
    if "unique" in on and "not_null" in on:
        return PRESENT, f"{pk} has unique + not_null"
    missing = ", ".join(t for t in ("unique", "not_null") if t not in on)
    return MISSING, f"PK '{pk}' is missing {missing}"


def _detect_en03(n: NodeFacts) -> tuple[str, str] | None:
    """EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test."""
    if n.resource_type != "model":
        return None
    pk = n.pk_column()
    fks = [c for c in n.id_columns() if c != pk]
    if not fks:
        return None
    missing = [c for c in fks if "relationships" not in n.tests_on(c)]
    if not missing:
        return PRESENT, f"all FK column(s) have relationships tests: {', '.join(fks)}"
    return MISSING, f"FK column(s) without a relationships test: {', '.join(missing)}"


# Registry: rule_code -> detector. Severity is derived from the catalogue's `detection`
# (deterministic -> blocker, hybrid -> warning) by the command layer.
DETECTORS: dict[str, Callable[[NodeFacts], tuple[str, str] | None]] = {
    "MD-01": _detect_md01,
    "TM-AU-01": _detect_tmau01,
    "MD-02": _detect_md02,
    "EN-01": _detect_en01,
    "EN-03": _detect_en03,
}


def load_node_facts(manifest_path: Path | str) -> list[NodeFacts]:
    return node_facts_from_manifest(json.loads(Path(manifest_path).read_text(encoding="utf-8")))
