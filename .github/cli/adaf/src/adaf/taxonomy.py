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

# BigQuery temporal types (for TM-* applicability from warehouse-resolved column types).
TEMPORAL_TYPES = frozenset({"DATE", "DATETIME", "TIMESTAMP", "TIME"})
# TZ-sensitive types: an instant (TIMESTAMP) vs a wall-clock (DATETIME) must be contracted (TM-SC-03).
TZ_SENSITIVE_TYPES = frozenset({"TIMESTAMP", "DATETIME"})


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
    columns: list[str]  # YAML-DECLARED columns (from manifest)
    contract_enforced: bool
    has_freshness: bool  # source declared a freshness block
    tests: list[AttachedTest] = field(default_factory=list)
    resolved_columns: dict[str, str] = field(default_factory=dict)  # warehouse-RESOLVED name->data_type (from catalog.json)

    def effective_columns(self) -> list[str]:
        """The best available column list: warehouse-resolved when present, else YAML-declared.

        Resolved columns (from ``catalog.json``, needs a build) are authoritative — they are the real
        shape, so key-based rules can be evaluated even on models whose YAML declares no columns.
        """
        return list(self.resolved_columns) if self.resolved_columns else self.columns

    def temporal_columns(self) -> list[str]:
        """Resolved columns whose type is a date/time type — sound applicability for TM-* rules."""
        return [c for c, t in self.resolved_columns.items() if t.upper() in TEMPORAL_TYPES]

    def tz_sensitive_columns(self) -> list[str]:
        """Resolved TIMESTAMP/DATETIME columns — the ones whose tz semantics must be contracted."""
        return [c for c, t in self.resolved_columns.items() if t.upper() in TZ_SENSITIVE_TYPES]

    def test_names(self) -> set[str]:
        return {t.name for t in self.tests}

    def tests_on(self, column: str) -> set[str]:
        return {t.name for t in self.tests if t.column and t.column.lower() == column.lower()}

    def id_columns(self) -> list[str]:
        """Columns that look like keys (``*_id`` / ``*_uuid`` / bare ``id``)."""
        return [c for c in self.effective_columns() if c.lower().endswith(("_id", "_uuid")) or c.lower() == "id"]

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


def _catalog_columns(catalog_path: Path | str | None) -> dict[str, dict[str, str]]:
    """Read catalog.json → {unique_id: {column_name: data_type}} (warehouse-RESOLVED columns).

    Empty when no catalog is given or it doesn't exist — the detectors then fall back to the manifest's
    YAML-declared columns. A catalog needs ``dbt docs generate`` (a build), so it is optional.
    """
    if catalog_path is None or not Path(catalog_path).exists():
        return {}
    data = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for uid, node in (data.get("nodes") or {}).items():
        out[uid] = {name: (col.get("type") or "") for name, col in (node.get("columns") or {}).items()}
    return out


def node_facts_from_manifest(data: dict, resolved: dict[str, dict[str, str]] | None = None) -> list[NodeFacts]:
    """Build NodeFacts for every model and source in a dbt manifest dict (the same shape dbt writes).

    ``resolved`` (from ``_catalog_columns``) supplies warehouse-resolved column types per node, enabling
    key-based and TM-* rules on models whose YAML declares no columns.
    """
    nodes = data.get("nodes") or {}
    sources = data.get("sources") or {}
    resolved = resolved or {}
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
            resolved_columns=resolved.get(uid, {}),
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


def _detect_tmsc03(n: NodeFacts) -> tuple[str, str] | None:
    """TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned.

    Applicability is SOUND (a resolved TIMESTAMP/DATETIME column is unambiguously tz-sensitive — needs
    a build/catalog to know). Passes iff the model enforces a contract (which pins each column's
    declared type, making TIMESTAMP-vs-DATETIME explicit)."""
    if n.resource_type != "model":
        return None
    tz_cols = n.tz_sensitive_columns()
    if not tz_cols:
        return None  # no tz-sensitive column resolved (or no catalog) → rule role doesn't apply
    if n.contract_enforced:
        return PRESENT, f"contract pins the type of tz-sensitive column(s): {', '.join(tz_cols)}"
    return MISSING, (
        f"tz-sensitive column(s) {', '.join(tz_cols)} have no type contract — pin TIMESTAMP vs DATETIME "
        "with contract.enforced + data_type"
    )


# Registry: rule_code -> detector. Severity is derived from the catalogue's `detection`
# (deterministic -> blocker, hybrid -> warning) by the command layer.
DETECTORS: dict[str, Callable[[NodeFacts], tuple[str, str] | None]] = {
    "MD-01": _detect_md01,
    "TM-AU-01": _detect_tmau01,
    "MD-02": _detect_md02,
    "EN-01": _detect_en01,
    "EN-03": _detect_en03,
    "TM-SC-03": _detect_tmsc03,
}


def load_node_facts(manifest_path: Path | str, catalog_path: Path | str | None = None) -> list[NodeFacts]:
    """Distil manifest (+ optional catalog.json for warehouse-resolved column types) into NodeFacts."""
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return node_facts_from_manifest(data, _catalog_columns(catalog_path))
