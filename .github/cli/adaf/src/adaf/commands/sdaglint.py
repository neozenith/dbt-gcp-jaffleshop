"""``adaf sdag check`` — the system-boundary obligation lint gate.

A "data product" is a NAMED selector in ``selectors.yml``. Each product has a *system boundary*
(see ``adaf.dbt.graph``): the members whose lineage crosses out of (``outbound``), into
(``inbound``), or both (``both``) the product's member set. Interior (``inner``) members are
exempt. This gate asserts that every boundary node carries the contractual artifacts a published
data product owes its neighbours — read straight from the manifest, no warehouse round-trip.

Rules (each has a stable ID; a violation is reported per boundary node × unmet rule)::

    MD-02      outbound model must declare an *enforced* data contract
    MD-11      outbound model must back at least one exposure
    MD-12      outbound model must back at least one semantic model
    TM-AU-01   inbound source must define a freshness policy
    MD-07      inbound node must have an Elementary volume-anomaly test

``both`` nodes are held to the union of the inbound + outbound rules that match their
``resource_type`` (so a model that is both inbound and outbound owes the outbound trio; a source
that is both owes the inbound pair).

Artifact detection from ``manifest.json`` (the literal definitions this gate enforces):

* **enforced contract** — the node's ``config.contract.enforced`` is exactly ``True``.
* **exposure** — the node's ``unique_id`` is in the union of every ``exposures[*].depends_on.nodes``.
* **semantic model** — the node's ``unique_id`` is in the union of every
  ``semantic_models[*].depends_on.nodes``.
* **freshness** — the source node's ``freshness`` value is present and non-null.
* **Elementary volume anomaly** (HEURISTIC) — some ``test`` node depends on the uid AND looks like
  an Elementary volume test: its ``test_metadata.namespace == "elementary"`` and
  ``test_metadata.name`` contains ``"volume"``; *or*, leniently, the test node's ``unique_id`` /
  ``name`` contains ``"volume_anomalies"``. dbt does not flag Elementary tests structurally, so
  this string match is a best-effort identifier — tune it in ``_is_volume_anomaly_test`` if your
  Elementary package names its test differently.

Suppressions: a violation is dropped when ``.adaf.yml`` (repo root) suppresses its rule ID for the
node's ``original_file_path`` (see ``adaf.suppression``). The artifact-detection helpers
(:class:`Artifacts`) and rule evaluation (:func:`evaluate_node`) are pure — they take a manifest
dict and return data — so they are unit-testable against a hand-built manifest with no dbt.
"""

# Standard Library
import argparse
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Local
from adaf import config, report
from adaf.dbt.defer import defer_state_dir
from adaf.dbt.graph import BOTH, INBOUND, INNER, OUTBOUND, Graph
from adaf.dbt.ls import ls_member_ids
from adaf.dbt.manifest_view import ManifestView
from adaf.dbt.runner import dbt_parse
from adaf.dbt.selection import describe, from_args, resolve_model_ids
from adaf.suppression import DEFAULT_ADAF_CONFIG, Suppressions, load_suppressions

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NodeInfo:
    """The boundary-relevant facts about one manifest node."""

    unique_id: str
    resource_type: str
    original_file_path: str


@dataclass(frozen=True)
class Artifacts:
    """The artifact 'sets' a manifest exposes, distilled for boundary-obligation checks.

    Every set holds ``unique_id``s. ``nodes`` maps each uid to its :class:`NodeInfo` so the gate
    can resolve a boundary node's ``resource_type`` (which rules apply) and ``original_file_path``
    (suppression matching). Built via :meth:`from_manifest`; pure thereafter.
    """

    nodes: dict[str, NodeInfo]
    contracts: frozenset[str]  # nodes with config.contract.enforced is True
    exposure_deps: frozenset[str]  # the union of exposures[*].depends_on.nodes
    semantic_deps: frozenset[str]  # the union of semantic_models[*].depends_on.nodes
    fresh_sources: frozenset[str]  # sources whose freshness is present/non-null
    volume_targets: frozenset[str]  # nodes an Elementary volume-anomaly test depends on
    # Inbound obligations are owned by the ENTRY-POINT MODEL (the boundary subject), satisfied via the
    # source(s) it reads — because only models are boundary subjects now, but the freshness / volume
    # artifact lives on the source feeding it. These are the models for which that source carries it.
    entry_models_with_fresh_source: frozenset[str]  # models reading ≥1 source with freshness
    entry_models_with_volume_monitor: frozenset[str]  # models reading ≥1 volume-tested source (or tested themselves)

    @classmethod
    def from_manifest(cls, data: dict[str, Any]) -> "Artifacts":
        """Distil an already-parsed manifest dict (convenience wrapper over :meth:`from_view`)."""
        return cls.from_view(ManifestView.from_dict(data))

    @classmethod
    def from_view(cls, view: ManifestView) -> "Artifacts":
        """Distil a dbt manifest view into the artifact sets the boundary rules check against."""
        node_info: dict[str, NodeInfo] = {}
        contracts: set[str] = set()
        volume_targets: set[str] = set()
        fresh_sources: set[str] = set()

        for uid, rec in view.records().items():
            node = rec.raw
            node_info[uid] = NodeInfo(uid, rec.resource_type, str(node.get("original_file_path") or ""))
            if rec.section == "sources":
                if node.get("freshness") is not None:
                    fresh_sources.add(uid)
                continue
            contract = (node.get("config") or {}).get("contract") or {}
            if contract.get("enforced") is True:
                contracts.add(uid)
            if rec.resource_type == "test" and _is_volume_anomaly_test(node):
                for dep in (node.get("depends_on") or {}).get("nodes", []):
                    volume_targets.add(dep)

        exposure_deps: set[str] = set()
        for exp in view.section("exposures").values():
            exposure_deps.update((exp.get("depends_on") or {}).get("nodes", []))

        semantic_deps: set[str] = set()
        for sm in view.section("semantic_models").values():
            semantic_deps.update((sm.get("depends_on") or {}).get("nodes", []))

        # Re-home the inbound obligations onto the entry-point model via its DIRECT source parents:
        # a model reading a fresh source satisfies freshness; reading a volume-tested source (or being
        # volume-tested itself) satisfies the volume obligation.
        models = {uid for uid, rec in view.records().items() if rec.resource_type == "model"}
        source_uids = {uid for uid, rec in view.records().items() if rec.resource_type == "source"}
        fresh_models: set[str] = set()
        volume_models = {uid for uid in volume_targets if uid in models}  # a model tested directly counts
        for parent, child in view.parent_edges():
            if child not in models or parent not in source_uids:
                continue
            if parent in fresh_sources:
                fresh_models.add(child)
            if parent in volume_targets:  # the source feeding this model is volume-monitored
                volume_models.add(child)

        return cls(
            nodes=node_info,
            contracts=frozenset(contracts),
            exposure_deps=frozenset(exposure_deps),
            semantic_deps=frozenset(semantic_deps),
            fresh_sources=frozenset(fresh_sources),
            volume_targets=frozenset(volume_targets),
            entry_models_with_fresh_source=frozenset(fresh_models),
            entry_models_with_volume_monitor=frozenset(volume_models),
        )


def _is_volume_anomaly_test(node: dict[str, Any]) -> bool:
    """HEURISTIC: does this ``test`` node look like an Elementary volume-anomaly test?

    Primary signal: ``test_metadata.namespace == "elementary"`` and ``test_metadata.name``
    contains ``"volume"``. Lenient fallback: the node's ``unique_id`` / ``name`` contains
    ``"volume_anomalies"`` (Elementary's default test name) — covers manifests where the
    ``test_metadata`` shape differs across dbt/Elementary versions.
    """
    meta = node.get("test_metadata") or {}
    namespace = str(meta.get("namespace") or "").lower()
    name = str(meta.get("name") or "").lower()
    if namespace == "elementary" and "volume" in name:
        return True
    blob = f"{node.get('unique_id') or ''}|{node.get('name') or ''}".lower()
    return "volume_anomalies" in blob


@dataclass(frozen=True)
class Rule:
    """One boundary obligation: which labels/resource-types it covers + how to detect it."""

    rule_id: str
    description: str
    labels: frozenset[str]  # boundary labels the rule applies to
    resource_types: frozenset[str] | None  # None = applies to any resource_type
    select: Callable[[Artifacts], frozenset[str]]  # the artifact set that satisfies it
    guidance: str  # one actionable sentence on how to fix the violation
    url: str  # link to the source docs for the obligation

    def applies(self, label: str, resource_type: str) -> bool:
        if label not in self.labels:
            return False
        return self.resource_types is None or resource_type in self.resource_types

    def satisfied(self, uid: str, artifacts: Artifacts) -> bool:
        return uid in self.select(artifacts)


# The rule registry. Outbound trio is model-only; inbound freshness is source-only; the inbound
# volume-anomaly obligation applies to any resource_type. `both` nodes match via the label sets.
RULES: list[Rule] = [
    Rule(
        "MD-02",
        "missing enforced data contract",
        frozenset({OUTBOUND, BOTH}),
        frozenset({"model"}),
        lambda a: a.contracts,
        guidance=(
            "Add `contract: {enforced: true}` to the model's config so its output schema is enforced at build time."
        ),
        url="https://docs.getdbt.com/docs/collaborate/govern/model-contracts",
    ),
    Rule(
        "MD-11",
        "missing exposure",
        frozenset({OUTBOUND, BOTH}),
        frozenset({"model"}),
        lambda a: a.exposure_deps,
        guidance=(
            "Define an exposure that lists this model under `depends_on` so its "
            "downstream consumers are documented and governed."
        ),
        url="https://docs.getdbt.com/docs/build/exposures",
    ),
    Rule(
        "MD-12",
        "missing semantic model",
        frozenset({OUTBOUND, BOTH}),
        frozenset({"model"}),
        lambda a: a.semantic_deps,
        guidance=(
            "Define a semantic model on top of this model so its entities, dimensions, "
            "and measures are governed in the semantic layer."
        ),
        url="https://docs.getdbt.com/docs/build/semantic-models",
    ),
    Rule(
        "TM-AU-01",
        "missing source freshness",
        frozenset({INBOUND, BOTH}),
        frozenset({"model"}),  # the inbound MODEL owns it; satisfied by the source(s) it reads
        lambda a: a.entry_models_with_fresh_source,
        guidance="Add a `freshness:` block (`warn_after`/`error_after`) to the source this entry model reads.",
        url="https://docs.getdbt.com/reference/resource-properties/freshness",
    ),
    Rule(
        "MD-07",
        "missing Elementary volume-anomaly test",
        frozenset({INBOUND, BOTH}),
        frozenset({"model"}),  # the inbound MODEL owns it; satisfied by a volume test on it or its source
        lambda a: a.entry_models_with_volume_monitor,
        guidance="Add an Elementary `volume_anomalies` test to the source this entry model reads (or to the model).",
        url="https://docs.elementary-data.com/data-tests/anomaly-detection-tests/volume-anomalies",
    ),
]


@dataclass(frozen=True)
class Violation:
    """A single unmet, unsuppressed obligation on a boundary node."""

    unique_id: str
    label: str
    rule_id: str
    description: str
    file_path: str
    guidance: str
    url: str


def evaluate_node(uid: str, label: str, artifacts: Artifacts, suppressions: Suppressions) -> list[Violation]:
    """Return the unmet, unsuppressed obligations for one boundary node (pure).

    ``inner`` nodes have no boundary obligations and yield nothing. Each applicable rule that is
    not satisfied and not suppressed (by rule ID + the node's ``original_file_path``) becomes a
    :class:`Violation`.
    """
    if label == INNER:
        return []
    info = artifacts.nodes.get(uid)
    resource_type = info.resource_type if info else ""
    file_path = info.original_file_path if info else ""
    violations: list[Violation] = []
    for rule in RULES:
        if not rule.applies(label, resource_type):
            continue
        if rule.satisfied(uid, artifacts):
            continue
        if suppressions.is_suppressed(rule.rule_id, file_path):
            continue
        violations.append(Violation(uid, label, rule.rule_id, rule.description, file_path, rule.guidance, rule.url))
    return violations


def _violations_to_findings(violations: list[Violation]) -> list[report.Finding]:
    """Down-convert violations to ``report.Finding`` (code=rule_id, message=description), grouped per
    boundary node and ordered by rule ID — the shared shape used by both the TUI and the JSON artifact."""
    by_node: dict[str, list[Violation]] = {}
    for v in violations:
        by_node.setdefault(v.unique_id, []).append(v)
    findings: list[report.Finding] = []
    for uid in sorted(by_node):
        for v in sorted(by_node[uid], key=lambda x: x.rule_id):
            findings.append(
                report.Finding(path=v.file_path or v.unique_id, severity="error", code=v.rule_id, message=v.description)
            )
    return findings


def _print_product_report(product: str, violations: list[Violation], *, color: bool) -> None:
    """Render a product's violations through :mod:`adaf.report`, grouped per boundary node.

    Emits a sqlfluff-style ``== [product: <name>] FAIL`` group header (to STDERR), then one
    :class:`report.Finding` per unmet obligation to STDOUT (``<path>: [error] <rule_id>
    <description>``), grouped per boundary node and ordered by rule ID. The per-rule guidance and doc
    URL are NOT repeated under each finding — they are aggregated once by
    :func:`_print_violation_summary` after the listing, so the same MD-12 advice isn't printed under
    every node that trips it. ``--color`` is honoured throughout.
    """
    report.render_file_header(f"product: {product}", "FAIL", color=color)
    for finding in _violations_to_findings(violations):
        print(report.render_finding(finding, color=color))


def _print_violation_summary(violations: list[Violation], *, color: bool) -> None:
    """After the per-node findings, tally the rule codes then print each rule's advice ONCE.

    Repeating a rule's guidance beneath every node that trips it is noise: a product missing
    contracts on four models printed the MD-02 fix four times. Instead we emit an aggregated count
    per rule code, then each rule's one-line guidance + doc URL a single time keyed by code — the
    concise, de-duplicated tail of the report. Both blocks go to STDERR (summary, not findings), so
    STDOUT stays a clean pipeable list of violations.
    """
    counts: dict[str, int] = {}
    advice: dict[str, tuple[str, str]] = {}  # rule_id -> (guidance, url), first occurrence wins
    descriptions: dict[str, str] = {}
    for v in violations:
        counts[v.rule_id] = counts.get(v.rule_id, 0) + 1
        advice.setdefault(v.rule_id, (v.guidance, v.url))
        descriptions.setdefault(v.rule_id, v.description)

    report.render_headline("violations by rule:", color=color, severity="error")
    for rule_id in sorted(counts):
        report.render_note(
            f"{rule_id} × {counts[rule_id]}  {descriptions[rule_id]}", color=color, indent=2, stream=sys.stderr
        )

    report.render_headline("how to fix:", color=color, severity="info")
    for rule_id in sorted(advice):
        guidance, url = advice[rule_id]
        report.render_note(f"{rule_id}  {guidance}", color=color, indent=2, stream=sys.stderr)
        report.render_note(f"see: {url}", color=color, indent=6, stream=sys.stderr)


def cmd_sdag_check(args: argparse.Namespace) -> int:
    """Lint a data product's boundary nodes against the system-boundary obligations.

    Scopes identically to the other checks (see ``adaf.dbt.selection``): ``--selector`` bounds the
    data product, the default intersects with git-changed files, and ``--all`` lints the whole
    product. The boundary is always *classified* over the product's FULL membership (so inside vs
    outside is correct) — the scope only decides which boundary nodes are *reported*. Models are
    scoped by the changed-files intersection; sources/seeds/snapshots (not ``models/*.sql``, so
    never in a git-diff of SQL) are always in scope for the product being checked.

    Returns 1 if any unsuppressed violation is found, else 0.
    """
    sel = from_args(args)
    color = report.should_colorize(args.color, sys.stdout)
    if getattr(args, "parse", False):
        log.info("sdag check: --parse — refreshing the manifest via `dbt parse`")
        dbt_parse(target=sel.target)

    view = ManifestView.load(args.manifest)  # parse once; both projections build from it
    artifacts = Artifacts.from_view(view)
    graph = Graph.from_view(view)

    adaf_config = config.under_root(DEFAULT_ADAF_CONFIG)
    suppressions = load_suppressions(adaf_config) if adaf_config is not None else Suppressions()

    # FULL product membership (models + sources + …) — needed so classify() sees the real boundary.
    state_dir = defer_state_dir(sel.defer_ref, target=sel.effective_defer_target) if sel.defer else None
    members = ls_member_ids(sel.selector, state_dir=state_dir, target=sel.target)

    # Report scope: models in `(changed or --all)` that are also in the selector (the shared scope
    # primitive), PLUS every non-model member (sources/seeds/snapshots aren't change-tracked SQL).
    scoped_models = resolve_model_ids(sel, view)
    member_models = {uid for uid in members if (info := artifacts.nodes.get(uid)) and info.resource_type == "model"}
    non_models = members - member_models  # sources/seeds/snapshots: always in scope for the product
    report_scope = scoped_models | non_models

    labels = graph.classify(members)
    violations: list[Violation] = []
    for uid, label in labels.items():
        if uid not in report_scope:
            continue
        violations.extend(evaluate_node(uid, label, artifacts, suppressions))

    rc = 1 if violations else 0
    json_out = getattr(args, "json_out", None)
    quiet = getattr(args, "quiet", False)
    if json_out is not None:
        report.write_findings_json(json_out, "sdag-check", rc, _violations_to_findings(violations))
    if quiet:
        return rc

    report.render_headline(
        f"# sdag check — system-boundary obligations — {describe(sel)}", color=color, severity="info"
    )
    if violations:
        _print_product_report(sel.selector, violations, color=color)
        # The findings list goes to STDOUT, the summary below to STDERR. Flush STDOUT first so the
        # order is deterministic even when STDOUT is a pipe (block-buffered): errors, then counts,
        # then advice — never the summary ahead of the listing it summarises.
        sys.stdout.flush()
        report.render_headline(
            f"sdag check: {len(violations)} violation(s) on {len({v.unique_id for v in violations})} "
            f"boundary node(s) in {describe(sel)}",
            color=color,
            severity="error",
        )
        _print_violation_summary(violations, color=color)
        return rc
    report.render_headline(f"sdag check: OK — boundary obligations met in {describe(sel)}.", color=color, severity="ok")
    return rc
