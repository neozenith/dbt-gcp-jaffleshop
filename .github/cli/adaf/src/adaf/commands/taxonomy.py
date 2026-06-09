"""``check taxonomy`` — run the deterministic catalogue detectors over the selected models.

Bridges the catalogue's ``detection`` field to runtime: for each rule with a registered detector
(``adaf.taxonomy.DETECTORS``), evaluate every in-scope node and report present / missing. Severity
comes from the catalogue — ``deterministic`` rules are **blockers** (a miss fails the gate),
``hybrid`` rules are advisory **warnings** (suppressible; the LLM ``review`` adjudicates the rest).

Scope: the SELECTED models (changed-only by default), PLUS every source (source-freshness, TM-AU-01,
is global hygiene and has no changed-file notion). ``--strict`` promotes warnings to failures.

The result dataclasses live in ``adaf.reports.taxonomy`` (re-exported here for back-compat).
"""

from argparse import Namespace

from adaf import config
from adaf.dbt import selection
from adaf.reports.taxonomy import SuppressedFinding, TaxonomyFinding, TaxonomyReport
from adaf.rules import get_rule
from adaf.suppression import Suppressions
from adaf.taxonomy import DETECTORS, MISSING, NOT_APPLICABLE, NodeFacts, load_node_facts
from adaf.utils.formatting import render_from_args

__all__ = ["SuppressedFinding", "TaxonomyFinding", "TaxonomyReport", "evaluate", "build_report", "cmd"]

# Map the catalogue's detection mode to a finding severity.
_SEVERITY = {"deterministic": "blocker", "hybrid": "warning"}


def evaluate(
    nodes: list[NodeFacts],
    in_scope_models: set[str],
    *,
    strict: bool,
    scope: str,
    suppressions: Suppressions | None = None,
) -> TaxonomyReport:
    """Run every registered detector over each in-scope node, producing one finding per (node, rule).

    A finding whose (rule, file) is suppressed (``adaf.yml`` glob or inline ``-- adaf-disable``) is
    dropped from ``findings`` and recorded under ``suppressed`` instead — so a silenced rule can
    never fail the gate, but the opt-out stays auditable.
    """
    findings: list[TaxonomyFinding] = []
    suppressed: list[SuppressedFinding] = []
    for n in nodes:
        # Models are gated only when selected; sources are always in scope (freshness is global).
        if n.resource_type == "model" and n.original_file_path not in in_scope_models:
            continue
        for code, detector in DETECTORS.items():
            result = detector(n)
            if result is None:
                continue  # the rule's role doesn't apply to this node
            status, detail = result
            if status == NOT_APPLICABLE:
                continue
            reason = suppressions.reason_for(code, n.original_file_path) if suppressions else None
            if reason is not None:
                if status == MISSING:  # only a would-be gap is worth recording as suppressed
                    suppressed.append(SuppressedFinding(n.name, code, reason))
                continue
            detection = (get_rule(code) or {}).get("detection", "hybrid")
            findings.append(
                TaxonomyFinding(
                    n.name, n.resource_type, code, detection, _SEVERITY.get(detection, "warning"), status, detail
                )
            )
    return TaxonomyReport(scope, findings, strict=strict, suppressed=suppressed)


def build_report(args: Namespace) -> TaxonomyReport:
    """Resolve selection + manifest, then evaluate. Shared by the subcommand and `check all`."""
    sel = selection.from_args(args)
    files = selection.resolve_model_files(sel)
    in_scope = {str(f) for f in files}
    manifest = config.under_root(args.manifest)
    if manifest is None or not manifest.exists():
        return TaxonomyReport(
            selection.describe(sel),
            [],
            strict=getattr(args, "strict", False),
            error=f"dbt manifest not found at '{manifest}'. Run `dbt parse` or pass --parse.",
        )
    catalog = config.under_root(getattr(args, "catalog", None))
    nodes = load_node_facts(manifest, catalog if catalog and catalog.exists() else None)
    suppressions = Suppressions.load(config.PROJECT_ROOT)
    return evaluate(
        nodes, in_scope, strict=getattr(args, "strict", False), scope=selection.describe(sel), suppressions=suppressions
    )


def cmd(args: Namespace) -> int:
    return render_from_args(build_report(args), args)
