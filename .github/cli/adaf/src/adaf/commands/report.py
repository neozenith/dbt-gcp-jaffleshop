"""``adaf report`` — a per-model markdown review of the testing taxonomy, generated mechanically.

Every row is produced by running the SAME detectors CI runs (``adaf.taxonomy.DETECTORS``) over the
manifest's ``NodeFacts``. Nothing is authored by hand, so there is nothing to hallucinate: a rule's
**applicability** is "the detector returned a result (not None)", and its **verdict** is the detector's
own status + the manifest fact that produced it. Each row cites its detector function and the rule's
catalogue entry (DAMA-UK6 dimension + ``applies_when`` + vignette), giving full lineage from finding →
code → fact → rule.

Rules WITHOUT a deterministic detector (the ``llm`` ones) are **not asserted per model** — that needs
judgement, so they are listed once, honestly, with their catalogue ``applies_when`` and a pointer to
``adaf review`` (whose output is an LLM artifact, not a deterministic claim).
"""

import logging
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from adaf import config, selection
from adaf.rules import all_rules, get_rule, load_catalog
from adaf.suppression import Suppressions
from adaf.taxonomy import DETECTORS, NOT_APPLICABLE, PRESENT, NodeFacts, load_node_facts

log = logging.getLogger(__name__)

_SEVERITY = {"deterministic": "blocker", "hybrid": "warning"}


def _detector_ref(code: str) -> str:
    """Code lineage for a rule's detector: function path + its one-line predicate (its docstring)."""
    fn = DETECTORS[code]
    doc = (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""
    return f"`adaf.taxonomy.{fn.__name__}` — {doc}"


def _tests_str(n: NodeFacts) -> str:
    items = []
    for t in n.tests:
        prefix = f"{t.namespace}." if t.namespace else ""
        items.append(f"`{prefix}{t.name}{f'({t.column})' if t.column else ''}`")
    return ", ".join(sorted(set(items))) or "none"


def _facts_block(n: NodeFacts) -> list[str]:
    lines = [
        "**Manifest facts** (the source of every verdict below — from `target/manifest.json`):",
        "",
        f"- Columns ({len(n.columns)}): {', '.join(f'`{c}`' for c in n.columns) or '—'}",
        f"- Tests present: {_tests_str(n)}",
    ]
    if n.resource_type == "model":
        lines.append(f"- Contract enforced: `{n.contract_enforced}`")
        lines.append(f"- Inferred PK: {f'`{n.pk_column()}`' if n.pk_column() else '(none identifiable)'}")
        fks = [c for c in n.id_columns() if c != n.pk_column()]
        lines.append(f"- Key (`*_id`/`*_uuid`) columns beyond the PK: {', '.join(f'`{c}`' for c in fks) or 'none'}")
        if not n.columns:
            lines.append(
                "- ⚠️ **No columns declared in this model's YAML** — so the key-based rules (EN-*) below "
                "report _n/a_ not because the model has no keys, but because none are declared to evaluate. "
                "Declaring columns is itself the first gap to close. (Columns here are YAML-declared, from "
                "the manifest — not warehouse-resolved.)"
            )
    else:
        lines.append(f"- Declares a freshness SLA: `{n.has_freshness}`")
    return lines


def _rule_rows(n: NodeFacts, suppressions: Suppressions) -> list[str]:
    """One table row per deterministic detector, applicable or not — all derived from the detector."""
    rows = []
    for code in DETECTORS:
        rule = get_rule(code) or {}
        dama = "/".join(rule.get("dama", []))
        result = DETECTORS[code](n)
        if result is None or (result and result[0] == NOT_APPLICABLE):
            applies, why_applies, verdict, evidence = (
                "—  no",
                f"role/precondition not met (rule applies_when: _{rule.get('applies_when', '')}_)",
                "n/a",
                "detector returned no finding for this node",
            )
        else:
            status, detail = result
            applies, why_applies = "✅ yes", f"applies_when: _{rule.get('applies_when', '')}_"
            reason = suppressions.reason_for(code, n.original_file_path)
            if reason is not None:
                verdict, evidence = "🟡 suppressed", f"{detail} — **suppressed**: {reason}"
            elif status == PRESENT:
                verdict, evidence = "✅ pass", detail
            else:
                verdict = "❌ " + _SEVERITY.get(rule.get("detection", "hybrid"), "warning")
                evidence = detail
        rows.append(f"| `{code}` | {dama} | {applies} | {why_applies} | {verdict} | {evidence} | {_detector_ref(code)} |")
    return rows


def _model_section(n: NodeFacts, suppressions: Suppressions) -> list[str]:
    head = f"### `{n.name}` — {n.resource_type}" + (f" (layer `{n.layer}`)" if n.layer else "")
    out = [head, ""]
    out += _facts_block(n)
    out += [
        "",
        "**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):",
        "",
        "| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |",
        "|---|---|---|---|---|---|---|",
    ]
    out += _rule_rows(n, suppressions)
    out.append("")
    return out


def _judgement_section() -> list[str]:
    out = [
        "## Rules requiring judgement (NOT asserted per-model here)",
        "",
        "These rules have no deterministic detector — their applicability depends on column semantics or "
        "intent that the manifest cannot prove (e.g. *is this column a ratio?*, *is this a refactor?*). "
        "To avoid hallucinating, this report does **not** assign them per-model verdicts. Their catalogue "
        "`applies_when` is listed below; the LLM `adaf review` is the (advisory, non-deterministic) source "
        "for model-by-model judgement on these — see the coverage matrices it posts to the PR.",
        "",
        "| Rule | DAMA-UK6 | detection | Applies when |",
        "|---|---|---|---|",
    ]
    coded = set(DETECTORS)
    for r in all_rules():
        if r["code"] in coded:
            continue
        out.append(f"| `{r['code']}` | {'/'.join(r['dama'])} | {r['detection']} | {r['applies_when']} |")
    out.append("")
    return out


def build_markdown(nodes: list[NodeFacts], in_scope_models: set[str], suppressions: Suppressions, scope: str) -> str:
    cat = load_catalog()
    models = [n for n in nodes if n.resource_type == "model" and n.original_file_path in in_scope_models]
    sources = [n for n in nodes if n.resource_type == "source"]
    models.sort(key=lambda n: (n.layer, n.name))
    sources.sort(key=lambda n: n.name)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = [
        "# Testing-taxonomy review — per-model, with full lineage",
        "",
        "> **Generated** by `adaf report` — every verdict below is produced by running the detectors in "
        "`adaf.taxonomy.DETECTORS` over `target/manifest.json`. No value is hand-authored. Re-generate with "
        "`uv run --directory dbt-jaffleshop adaf report --all -o <file>`.",
        "",
        f"- Generated (UTC): {ts}",
        f"- Catalogue version: `{cat['version']}` ({len(cat['rules'])} rules) · scope: {scope}",
        f"- Detectors applied: {', '.join(f'`{c}`' for c in DETECTORS)} (the rules whose applicability + "
        "pass/fail are statically decidable)",
        "",
        "**How to read a row:** *Applies?* = the detector matched this node's role/structure. *Verdict* = the "
        "detector's status (pass / blocker / warning / suppressed). *Evidence* = the exact manifest fact. "
        "*Detector* = the function that decided it (and its one-line predicate).",
        "",
        "## Models",
        "",
    ]
    for n in models:
        out += _model_section(n, suppressions)
    out += ["## Sources", ""]
    for n in sources:
        out += _model_section(n, suppressions)
    out += _judgement_section()
    return "\n".join(out)


def cmd(args: Namespace) -> int:
    sel = selection.from_args(args)
    files = selection.resolve_model_files(sel)
    in_scope = {str(f) for f in files}
    manifest = config.under_root(args.manifest)
    if not Path(manifest).exists():
        raise FileNotFoundError(f"dbt manifest not found at '{manifest}'. Run `dbt parse` or pass --parse.")
    nodes = load_node_facts(manifest)
    md = build_markdown(nodes, in_scope, Suppressions.load(config.PROJECT_ROOT), selection.describe(sel))
    out = config.under_root(args.output) if getattr(args, "output", None) else None
    if out:
        Path(out).write_text(md, encoding="utf-8")
        log.info("wrote per-model taxonomy review to %s", out)
    else:
        print(md)
    return 0
