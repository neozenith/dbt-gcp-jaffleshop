"""Enrich each selector's cache file with the FULL sdag-check compliance picture.

The sdag viewer (``adaf products generate``) reads one cache file per data product at
``tmp/adaf_cache/selectors/<selector>.json`` (see ``adaf.dbt.cache``). On its own that file carries
only membership + boundary layout — so a product's *compliance* (does each boundary node carry the
contractual artifacts it owes?) is invisible in the viewer. This module computes exactly the
obligation results ``adaf sdag check`` reports and writes them back into the same cache file,
additively, under two keys:

* ``compliance`` — a product-level rollup (total / passed / failed / suppressed obligations + a %).
* ``annotations`` — per boundary node, its boundary label and, for every applicable obligation rule,
  a ``pass`` / ``fail`` / ``suppressed`` status with a human message.

The obligation logic is NOT reimplemented here: the rule registry (:data:`~adaf.commands.sdaglint.RULES`),
the artifact distillation (:class:`~adaf.commands.sdaglint.Artifacts`) and the per-node evaluation
(:func:`~adaf.commands.sdaglint.evaluate_node`) are imported from the lint module and called.
``evaluate_node`` owns the authoritative "is this a violation?" decision — including honouring the
suppressions exactly the way ``adaf sdag check`` does (a suppressed obligation is not a failure).

Pure where it can be: :func:`compute_compliance` takes a :class:`~adaf.dbt.manifest_view.ManifestView`,
a member set and resolved :class:`~adaf.suppression.Suppressions`, and returns plain JSON-able dicts —
unit-testable with a hand-built manifest, no dbt. Only :func:`enrich_selector_cache` and
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
from adaf.dbt.manifest_view import ManifestView
from adaf.graph import INNER, Graph
from adaf.suppression import Suppressions

log = logging.getLogger(__name__)

# Per-rule statuses written into the per-node annotations.
SATISFIED = "pass"
FAIL = "fail"
SUPPRESSED = "suppressed"

_STATUS_MESSAGE = {
    SATISFIED: "satisfied",
    SUPPRESSED: "suppressed via adaf.yml / inline",
}


def _node_rule_entries(uid: str, label: str, artifacts: Artifacts, suppressions: Suppressions) -> list[dict[str, Any]]:
    """The per-rule status list for one boundary node (one entry per *applicable* obligation).

    ``evaluate_node`` is the authority on failures (it applies the rule registry AND the
    suppressions just like ``adaf sdag check``). A rule that applies but is absent from that list
    is either satisfied or suppressed; we distinguish the two with ``Rule.satisfied``.
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
    a boundary label via :class:`~adaf.graph.Graph`, and every non-``internal`` node is evaluated
    against its applicable obligations. ``internal`` members carry no obligations and are omitted.

    Returns ``{"compliance": {...rollup...}, "annotations": {uid: {"boundary", "rules": [...]}}}``.
    ``compliance_pct`` treats a suppressed obligation as compliant (it does not fail the product),
    matching ``adaf sdag check``'s suppression semantics.
    """
    artifacts = Artifacts.from_view(view)
    graph = Graph.from_view(view)
    labels = graph.classify(members)

    annotations: dict[str, dict[str, Any]] = {}
    total = passed = failed = suppressed = 0
    failed_nodes = 0
    for uid in sorted(labels):
        label = labels[uid]
        if label == INNER:
            continue
        entries = _node_rule_entries(uid, label, artifacts, suppressions)
        annotations[uid] = {"boundary": label, "rules": entries}
        node_failed = False
        for entry in entries:
            total += 1
            if entry["status"] == SATISFIED:
                passed += 1
            elif entry["status"] == FAIL:
                failed += 1
                node_failed = True
            else:
                suppressed += 1
        if node_failed:
            failed_nodes += 1

    compliant = total - failed  # passed + suppressed (a suppressed obligation does not fail)
    compliance_pct = round(100.0 * compliant / total, 1) if total else 100.0
    rollup = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "suppressed": suppressed,
        "compliance_pct": compliance_pct,
        "boundary_nodes": len(annotations),
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
    otherwise. The cache file is expected to exist (the generate flow writes it first); a missing
    file is a real bug and raises, never a silent skip.
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


def enrich_all(root: Path, view: ManifestView, resolved: dict[str, set[str]]) -> None:
    """Enrich every resolved selector's cache file with its compliance results.

    Loads the suppressions once (shared across all products) and merges compliance into each
    selector's cache file. A per-selector failure is logged and re-raised — enrichment is a real
    requirement of the generate flow, not a best-effort extra.
    """
    suppressions = Suppressions.load(config.project_root())
    for name, members in resolved.items():
        enrich_selector_cache(root, name, view, members, suppressions)
        log.debug("sdag annotations: %s (%d members)", name, len(members))
    log.info("sdag: enriched %d selector cache file(s) with compliance annotations", len(resolved))
