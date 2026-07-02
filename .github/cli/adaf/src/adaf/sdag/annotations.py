"""Enrich each selector's cache file with the FULL sdag-check compliance picture.

The sdag viewer (``adaf sdag generate``) reads one cache file per data product at
``tmp/adaf_cache/selectors/<selector>.json`` (see ``adaf.dbt.cache``). On its own that file
carries only membership + boundary layout — so on a fresh parse a product's *compliance* (does
each boundary node carry the contractual artifacts it owes?) is invisible in the viewer. This
module computes exactly the obligation results ``adaf sdag check`` reports and writes them back
into the same cache file, additively, under two keys:

* ``compliance`` — a product-level rollup (total / passed / failed / suppressed obligations and a
  compliance %).
* ``annotations`` — per boundary node, its boundary label and, for every applicable obligation
  rule, a ``pass`` / ``fail`` / ``suppressed`` status with a human message.

The obligation logic is NOT reimplemented here: the rule registry (:data:`~adaf.commands.sdaglint.RULES`),
the artifact distillation (:class:`~adaf.commands.sdaglint.Artifacts`) and the per-node evaluation
(:func:`~adaf.commands.sdaglint.evaluate_node`) are imported from the lint module and called.
``evaluate_node`` owns the authoritative "is this a violation?" decision — including honouring the
``.adaf.yml`` suppressions exactly the way ``adaf sdag check`` does (a suppressed obligation is not
a failure). The residual "applicable but neither satisfied nor failed" is, by construction, a
suppressed obligation, so the per-rule status is derived without forking any lint logic.

Pure where it can be: :func:`compute_compliance` takes a :class:`~adaf.dbt.manifest_view.ManifestView`,
a member set and resolved :class:`~adaf.suppression.Suppressions`, and returns plain JSON-able
dicts — unit-testable with a hand-built manifest, no dbt. Only :func:`enrich_selector_cache` and
:func:`enrich_all` touch disk (merging into the existing cache file, never clobbering it).
"""

# Standard Library
import json
import logging
from pathlib import Path
from typing import Any

# Local
from adaf import config
from adaf.commands.sdaglint import RULES, Artifacts, evaluate_node
from adaf.dbt import cache
from adaf.dbt.graph import INNER, Graph
from adaf.dbt.manifest_view import ManifestView
from adaf.suppression import DEFAULT_ADAF_CONFIG, Suppressions, load_suppressions

log = logging.getLogger(__name__)

# Per-rule statuses written into the per-node annotations.
SATISFIED = "pass"
FAIL = "fail"
SUPPRESSED = "suppressed"

_STATUS_MESSAGE = {
    SATISFIED: "satisfied",
    SUPPRESSED: "suppressed via .adaf.yml",
}


def _node_rule_entries(uid: str, label: str, artifacts: Artifacts, suppressions: Suppressions) -> list[dict[str, Any]]:
    """The per-rule status list for one boundary node (one entry per *applicable* obligation).

    ``evaluate_node`` is the authority on failures (it applies the rule registry AND the
    suppressions just like ``adaf sdag check``). A rule that applies but is absent from that list
    is either satisfied or suppressed; we distinguish the two with ``Rule.satisfied`` so the viewer
    can tell an excused obligation from a met one.
    """
    info = artifacts.nodes.get(uid)
    resource_type = info.resource_type if info else ""
    failed_rule_ids = {v.rule_id for v in evaluate_node(uid, label, artifacts, suppressions)}
    entries: list[dict[str, Any]] = []
    for rule in RULES:
        if not rule.applies(label, resource_type):
            continue
        if rule.rule_id in failed_rule_ids:
            status = FAIL
            message = rule.description
        elif rule.satisfied(uid, artifacts):
            status = SATISFIED
            message = _STATUS_MESSAGE[SATISFIED]
        else:
            status = SUPPRESSED
            message = _STATUS_MESSAGE[SUPPRESSED]
        entries.append(
            {
                "rule_id": rule.rule_id,
                "description": rule.description,
                "status": status,
                "message": message,
                "guidance": rule.guidance,
                "url": rule.url,
            }
        )
    return entries


def compute_compliance(view: ManifestView, members: set[str], suppressions: Suppressions) -> dict[str, Any]:
    """Compute the compliance rollup + per-node annotations for one data product (pure).

    ``members`` is the product's FULL resolved membership; each data-node member is classified into
    a boundary label via :class:`~adaf.dbt.graph.Graph`, and every non-``inner`` node is evaluated
    against its applicable obligations. ``inner`` members carry no obligations and are omitted.

    Returns ``{"compliance": {...rollup...}, "annotations": {uid: {"boundary", "rules", "compliance_pct",
    "total", "passed", "failed", "suppressed"}}}``, all JSON-serialisable. Each node carries a PARTIAL
    ``compliance_pct`` = ``(passed + suppressed) / total`` (a suppressed obligation counts as compliant);
    the product ``compliance_pct`` ROLLS these up as the mean of the per-node percentages — softer than
    the old obligation-weighted ratio, and never a binary node fail.
    """
    artifacts = Artifacts.from_view(view)
    graph = Graph.from_view(view)
    attributed = graph.attribute(members)

    annotations: dict[str, dict[str, Any]] = {}
    total = passed = failed = suppressed = 0
    failed_nodes = 0
    node_pcts: list[float] = []
    for uid in sorted(attributed):
        label = attributed[uid]["boundary"]
        attribution = attributed[uid]["attribution"]
        if label == INNER:
            # Inner models carry no obligations, but record WHY they were labelled inner (the
            # attribution) so the boundary algorithm is debuggable. They do NOT count toward the roll-up.
            annotations[uid] = {
                "boundary": label,
                "attribution": attribution,
                "rules": [],
                "compliance_pct": 100.0,
                "total": 0,
                "passed": 0,
                "failed": 0,
                "suppressed": 0,
            }
            continue
        entries = _node_rule_entries(uid, label, artifacts, suppressions)
        n_total = n_passed = n_failed = n_suppressed = 0
        for entry in entries:
            n_total += 1
            if entry["status"] == SATISFIED:
                n_passed += 1
            elif entry["status"] == FAIL:
                n_failed += 1
            else:
                n_suppressed += 1
        # PARTIAL per-node compliance: a node 2-of-3 compliant scores 66.7%, not a binary fail. A
        # suppressed obligation counts as compliant (it does not fail). A node with no obligations is 100%.
        n_compliant = n_passed + n_suppressed
        node_pct = round(100.0 * n_compliant / n_total, 1) if n_total else 100.0
        annotations[uid] = {
            "boundary": label,
            "attribution": attribution,
            "rules": entries,
            "compliance_pct": node_pct,
            "total": n_total,
            "passed": n_passed,
            "failed": n_failed,
            "suppressed": n_suppressed,
        }
        total += n_total
        passed += n_passed
        failed += n_failed
        suppressed += n_suppressed
        node_pcts.append(node_pct)
        if n_failed:
            failed_nodes += 1

    # ROLL UP the per-node partials: each boundary node weighted equally (the mean of node %s), so one
    # node with many obligations can't dominate and partial node credit carries through to the product.
    compliance_pct = round(sum(node_pcts) / len(node_pcts), 1) if node_pcts else 100.0
    rollup = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "suppressed": suppressed,
        "compliance_pct": compliance_pct,
        "boundary_nodes": len(node_pcts),  # the non-inner (obligation-bearing) nodes only
        "failed_nodes": failed_nodes,
    }
    return {"compliance": rollup, "annotations": annotations}


def enrich_selector_cache(
    root: Path,
    name: str,
    view: ManifestView,
    members: set[str],
    suppressions: Suppressions,
) -> Path:
    """Merge a product's compliance results into its existing selector cache file (additive).

    Reads the file ``adaf.dbt.cache`` already wrote (membership + boundary layout + fingerprint),
    adds the ``compliance`` rollup and per-node ``annotations`` keys, and writes it back unchanged
    otherwise. The cache file is expected to exist (``adaf sdag generate`` writes it before this
    step runs); a missing file is a real bug and raises, never a silent skip.
    """
    path = cache.selector_cache_path(root, name)
    if not path.exists():
        raise FileNotFoundError(
            f"selector cache for '{name}' not found at '{path}'; enrich runs after the cache is written"
        )
    blob = json.loads(path.read_text(encoding="utf-8"))
    blob.update(compute_compliance(view, members, suppressions))
    path.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    log.debug("sdag annotations: enriched %s compliance into %s", name, path)
    return path


def _load_suppressions() -> Suppressions:
    """Resolve ``.adaf.yml`` from the project root exactly as ``adaf sdag check`` does."""
    adaf_config = config.under_root(DEFAULT_ADAF_CONFIG)
    return load_suppressions(adaf_config) if adaf_config is not None else Suppressions()


def enrich_all(root: Path, view: ManifestView, resolved: dict[str, set[str]]) -> None:
    """Enrich every resolved selector's cache file with its compliance results.

    Loads the suppressions once (shared across all products) and merges compliance into each
    selector's cache file. A per-selector failure is logged and re-raised — enrichment is a real
    requirement of the generate flow, not a best-effort extra.
    """
    suppressions = _load_suppressions()
    for name, members in resolved.items():
        enrich_selector_cache(root, name, view, members, suppressions)
        log.debug("sdag annotations: %s (%d members)", name, len(members))
    log.info("sdag: enriched %d selector cache file(s) with compliance annotations", len(resolved))
