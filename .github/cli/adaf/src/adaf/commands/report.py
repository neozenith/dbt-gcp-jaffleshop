"""``adaf report`` — a per-model markdown review of the testing taxonomy, generated mechanically.

Every deterministic verdict is produced by running the SAME detectors CI runs
(``adaf.taxonomy.DETECTORS``) over the manifest (+ optional ``catalog.json`` for warehouse-resolved
column types). Nothing is hand-authored, so there is nothing to hallucinate: a rule's
**applicability** is "the detector returned a result", its **verdict** is the detector's status, and its
**evidence** is the exact manifest/catalog fact. Each row cites the detector function and the rule's
catalogue entry (DAMA-UK6 + ``applies_when``).

With ``--review <adaf review --json>``, the report also **reconciles the LLM's findings against the
deterministic ground truth** and flags every disagreement — the false-positive / false-negative
worklist. A rule with a detector is the yardstick; a rule without one is shown as the LLM asserted it,
explicitly marked *unverified*.
"""

import json
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
# adaf review status -> a comparable verdict token.
_LLM_MAP = {"applicable_present": "present", "applicable_missing": "gap", "not_applicable": "n/a"}


# ─── facts ────────────────────────────────────────────────────────────────────


def _detector_ref(code: str) -> str:
    fn = DETECTORS[code]
    doc = (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""
    return f"`adaf.taxonomy.{fn.__name__}` — {doc}"


def _tests_str(n: NodeFacts) -> str:
    items = []
    for t in n.tests:
        prefix = f"{t.namespace}." if t.namespace else ""
        items.append(f"`{prefix}{t.name}{f'({t.column})' if t.column else ''}`")
    return ", ".join(sorted(set(items))) or "none"


def _columns_line(n: NodeFacts) -> str:
    if n.resolved_columns:
        shown = ", ".join(f"`{c}`:{t}" for c, t in list(n.resolved_columns.items())[:24])
        note = "" if n.columns else "  ⚠️ (0 declared in YAML — a documentation gap; these are warehouse-resolved)"
        return f"- Columns ({len(n.resolved_columns)} warehouse-resolved from `catalog.json`): {shown}{note}"
    return f"- Columns ({len(n.columns)} YAML-declared; no catalog): {', '.join(f'`{c}`' for c in n.columns) or '—'}"


def _facts_block(n: NodeFacts) -> list[str]:
    lines = [
        "**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):",
        "",
        _columns_line(n),
        f"- Tests present: {_tests_str(n)}",
    ]
    if n.resource_type == "model":
        lines.append(f"- Contract enforced: `{n.contract_enforced}`")
        lines.append(f"- Inferred PK: {f'`{n.pk_column()}`' if n.pk_column() else '(none identifiable)'}")
        fks = [c for c in n.id_columns() if c != n.pk_column()]
        lines.append(f"- Key (`*_id`/`*_uuid`) columns beyond the PK: {', '.join(f'`{c}`' for c in fks) or 'none'}")
        tz = n.tz_sensitive_columns()
        if tz:
            lines.append(f"- TZ-sensitive (TIMESTAMP/DATETIME) columns: {', '.join(f'`{c}`' for c in tz)}")
        if not n.resolved_columns and not n.columns:
            lines.append("- ⚠️ **No columns known** (no YAML and no catalog) — key/time rules below report _n/a_.")
    else:
        lines.append(f"- Declares a freshness SLA: `{n.has_freshness}`")
    return lines


# ─── deterministic verdicts ───────────────────────────────────────────────────


def _det_verdict(n: NodeFacts, code: str, suppressions: Suppressions) -> tuple[str, str]:
    """(token, evidence) for a rule on a node. token ∈ pass | gap | n/a | suppressed | no-detector."""
    if code not in DETECTORS:
        return "no-detector", ""
    result = DETECTORS[code](n)
    if result is None or result[0] == NOT_APPLICABLE:
        return "n/a", "detector matched no role/precondition on this node"
    status, detail = result
    if suppressions.reason_for(code, n.original_file_path) is not None:
        return "suppressed", detail
    return ("pass" if status == PRESENT else "gap"), detail


def _det_display(token: str, rule: dict) -> str:
    return {
        "pass": "✅ pass",
        "gap": "❌ " + _SEVERITY.get(rule.get("detection", "hybrid"), "warning"),
        "n/a": "— n/a",
        "suppressed": "🟡 suppressed",
        "no-detector": "_(no detector)_",
    }[token]


def _rule_rows(n: NodeFacts, suppressions: Suppressions) -> list[str]:
    rows = []
    for code in DETECTORS:
        rule = get_rule(code) or {}
        token, evidence = _det_verdict(n, code, suppressions)
        applies = "—  no" if token == "n/a" else "✅ yes"
        why = (
            f"applies_when: _{rule.get('applies_when', '')}_"
            if token != "n/a"
            else f"role/precondition not met (applies_when: _{rule.get('applies_when', '')}_)"
        )
        ev = evidence
        if token == "suppressed":
            ev = f"{evidence} — **suppressed**: {suppressions.reason_for(code, n.original_file_path)}"
        rows.append(
            f"| `{code}` | {'/'.join(rule.get('dama', []))} | {applies} | {why} | {_det_display(token, rule)} | "
            f"{ev or '—'} | {_detector_ref(code)} |"
        )
    return rows


# ─── LLM reconciliation ───────────────────────────────────────────────────────


def llm_index(review: dict) -> dict[str, dict[str, str]]:
    """{model_name: {rule_code: comparable_verdict}} from `adaf review --json` output."""
    result = review.get("result", review)
    out: dict[str, dict[str, str]] = {}
    for m in result.get("models", []):
        verdicts: dict[str, str] = {}
        for f in m.get("findings", []):
            code = f.get("rule_code")
            if code:
                status = str(f.get("status") or "?")
                verdicts[code] = _LLM_MAP.get(status, status)
        out[m.get("model", "")] = verdicts
    return out


def _flag(det: str, llm: str | None) -> str:
    """Reconcile a deterministic token vs an LLM verdict → a reviewer-facing assessment."""
    if llm is None:
        return "·"  # the LLM emitted nothing for this (rule, model)
    table = {
        ("pass", "present"): "✅ agree (present)",
        ("gap", "gap"): "✅ agree (gap)",
        ("n/a", "n/a"): "✅ agree (n/a)",
        ("suppressed", "n/a"): "✅ suppressed / LLM n/a",
        ("pass", "gap"): "🔴 **LLM FALSE POSITIVE** — flagged a gap, but the test exists",
        ("gap", "present"): "🔴 **LLM FALSE NEGATIVE** — missed a real gap (claimed covered)",
        ("n/a", "present"): "🟠 applicability — LLM says present; deterministic finds the rule n/a here",
        ("n/a", "gap"): "🟠 applicability — LLM flags a gap; deterministic finds the rule n/a here",
        ("pass", "n/a"): "🟠 applicability — LLM marked n/a; deterministic says it applies (and passes)",
        ("gap", "n/a"): "🟠 applicability — LLM marked n/a; deterministic says it applies (and is a gap)",
        ("suppressed", "gap"): "🟡 suppressed deterministically; LLM still flags it (review the suppression)",
        ("suppressed", "present"): "🟡 suppressed deterministically; LLM marks present",
        ("no-detector", "present"): "⚪ unverified — no deterministic detector; LLM judgement only",
        ("no-detector", "gap"): "⚪ unverified — no deterministic detector; LLM judgement only",
        ("no-detector", "n/a"): "· unverified n/a (no detector)",
    }
    return table.get((det, llm), f"? {det} vs {llm}")


def _reconcile_rows(n: NodeFacts, suppressions: Suppressions, llm: dict[str, str]) -> list[tuple[int, str]]:
    """(sort_rank, row) reconciliation rows for this model. Lower rank = more urgent (FP/FN first)."""
    codes = list(DETECTORS) + [c for c in llm if c not in DETECTORS and llm[c] in ("present", "gap")]
    rank = {"🔴": 0, "🟠": 1, "🟡": 2, "⚪": 3}
    rows: list[tuple[int, str]] = []
    for code in dict.fromkeys(codes):
        rule = get_rule(code) or {}
        det_token, evidence = _det_verdict(n, code, suppressions)
        llm_v = llm.get(code)
        assessment = _flag(det_token, llm_v)
        r = next((v for k, v in rank.items() if assessment.startswith(k)), 9)
        det_cell = _det_display(det_token, rule) + (f" — {evidence}" if evidence and det_token in ("gap", "pass") else "")
        llm_cell = llm_v or "_(not emitted)_"
        rows.append((r, f"| `{code}` | {'/'.join(rule.get('dama', []))} | {det_cell} | {llm_cell} | {assessment} |"))
    return sorted(rows, key=lambda t: (t[0], t[1]))


# ─── sections ─────────────────────────────────────────────────────────────────


def _model_section(n: NodeFacts, suppressions: Suppressions, llm_idx: dict[str, dict[str, str]] | None) -> list[str]:
    out = [f"### `{n.name}` — {n.resource_type}" + (f" (layer `{n.layer}`)" if n.layer else ""), ""]
    out += _facts_block(n)
    out += [
        "",
        "**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):",
        "",
        "| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |",
        "|---|---|---|---|---|---|---|",
        *_rule_rows(n, suppressions),
        "",
    ]
    if llm_idx is not None:
        llm = llm_idx.get(n.name, {})
        out += [
            "**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):",
            "",
            "| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |",
            "|---|---|---|---|---|",
            *[row for _r, row in _reconcile_rows(n, suppressions, llm)],
            "",
        ]
    return out


def _fpfn_summary(nodes: list[NodeFacts], suppressions: Suppressions, llm_idx: dict[str, dict[str, str]]) -> list[str]:
    """The worklist: every LLM-vs-deterministic disagreement across all models, most-urgent first."""
    rows: list[tuple[int, str]] = []
    rank = {"🔴": 0, "🟠": 1, "🟡": 2}
    for n in nodes:
        llm = llm_idx.get(n.name, {})
        for code in dict.fromkeys(list(DETECTORS) + list(llm)):
            det_token, evidence = _det_verdict(n, code, suppressions)
            assessment = _flag(det_token, llm.get(code))
            r = next((v for k, v in rank.items() if assessment.startswith(k)), None)
            if r is None:
                continue  # only disagreements go on the worklist
            rows.append((r, f"| `{n.name}` | `{code}` | {_det_display(det_token, get_rule(code) or {})} "
                            f"| {llm.get(code)} | {assessment} | {evidence or '—'} |"))
    out = [
        "## False-positive / false-negative worklist",
        "",
        "Every place the LLM `adaf review` disagrees with the deterministic ground truth. "
        "🔴 = a verifiable LLM error (a detector proves it wrong); 🟠 = an applicability disagreement to "
        "adjudicate; 🟡 = the project suppressed it but the LLM still raised it. Agreements are omitted here "
        "(they appear per-model below).",
        "",
    ]
    if not rows:
        return out + ["_No disagreements: the LLM matched the deterministic verdict on every detector-backed rule._", ""]
    out += [
        "| Model | Rule | Deterministic | LLM | Assessment | Evidence (fact) |",
        "|---|---|---|---|---|---|",
        *[row for _r, row in sorted(rows, key=lambda t: (t[0], t[1]))],
        "",
    ]
    return out


def _judgement_section() -> list[str]:
    out = [
        "## Rules with no deterministic detector",
        "",
        "These rules' applicability depends on column semantics or intent the manifest/catalog cannot prove "
        "(e.g. *is this numeric a ratio?*, *is this PR a refactor?*). The report does **not** assert them "
        "deterministically; in the reconciliation above they show as ⚪ *unverified* — the LLM's judgement, "
        "for you to confirm. Their catalogue `applies_when` is the reference:",
        "",
        "| Rule | DAMA-UK6 | detection | Applies when |",
        "|---|---|---|---|",
    ]
    coded = set(DETECTORS)
    out += [
        f"| `{r['code']}` | {'/'.join(r['dama'])} | {r['detection']} | {r['applies_when']} |"
        for r in all_rules()
        if r["code"] not in coded
    ]
    return out + [""]


def build_markdown(
    nodes: list[NodeFacts],
    in_scope_models: set[str],
    suppressions: Suppressions,
    scope: str,
    review: dict | None = None,
) -> str:
    cat = load_catalog()
    models = sorted(
        (n for n in nodes if n.resource_type == "model" and n.original_file_path in in_scope_models),
        key=lambda n: (n.layer, n.name),
    )
    sources = sorted((n for n in nodes if n.resource_type == "source"), key=lambda n: n.name)
    llm_idx = llm_index(review) if review is not None else None
    has_catalog = any(n.resolved_columns for n in nodes)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = [
        "# Testing-taxonomy review — per-model, with full lineage",
        "",
        "> **Generated** by `adaf report` — deterministic verdicts come from running "
        "`adaf.taxonomy.DETECTORS` over the manifest"
        + (" + `catalog.json` (warehouse-resolved columns)" if has_catalog else " (no catalog — YAML-declared columns)")
        + ". No deterministic value is hand-authored. Re-generate: "
        "`uv run --directory dbt-jaffleshop adaf report --all --catalog target/catalog.json "
        "--review review.json -o <file>`.",
        "",
        f"- Generated (UTC): {ts}",
        f"- Catalogue version: `{cat['version']}` ({len(cat['rules'])} rules) · scope: {scope}",
        f"- Deterministic detectors: {', '.join(f'`{c}`' for c in DETECTORS)}",
        f"- Warehouse-resolved columns available: **{has_catalog}**"
        + ("" if has_catalog else " (run `dbt docs generate` for richer key/time coverage)"),
    ]
    if llm_idx is not None:
        usage = (review or {}).get("usage", {})
        out.append(
            f"- LLM review reconciled: **yes** — {usage.get('calls', '?')} call(s), "
            f"{usage.get('total_tokens', '?')} tokens (from `adaf review --json`)"
        )
    out += [
        "",
        "**How to read it:** *Deterministic* is the yardstick (a detector + a fact). *LLM* is what "
        "`adaf review` claimed. *Assessment* flags 🔴 verifiable LLM errors, 🟠 applicability disagreements, "
        "🟡 suppressed-but-flagged, ⚪ unverified (no detector). Start with the worklist, then drill into the model.",
        "",
        "<details><summary><b>Detector caveats — read before trusting a 🔴/🟠</b></summary>",
        "",
        "The detectors are deterministic but heuristic about *which column plays which role*. Knowing the "
        "heuristic tells you whether a flag is a true LLM error or a detector limit:",
        "",
        "- **MD-01** counts a model-level `unique` **or** `dbt_utils.unique_combination_of_columns` as a grain "
        "test. So a 🔴 *false positive* here means *a uniqueness test exists* — if the LLM wanted an explicit "
        "`unique_combination_of_columns`, that is a stricter-style preference, not a hallucinated fact.",
        "- **EN-01** infers the PK as `<model>_id` (singularised) or the **sole** `*_id`/`*_uuid` column. A model "
        "with several key columns yields *no identifiable PK* → EN-01 shows **n/a** (a detector limit, surfaced "
        "as 🟠 if the LLM asserts it — not an LLM error).",
        "- **EN-03** treats every non-PK `*_id`/`*_uuid` column as a FK needing a `relationships` test; when the PK "
        "isn't identified it may over-include a key as a FK.",
        "- **TM-SC-03** needs `catalog.json` (a build) to see column types; without it, it reports n/a.",
        "- Columns are **warehouse-resolved** from `catalog.json` when present (authoritative), else YAML-declared.",
        "",
        "</details>",
        "",
    ]
    if llm_idx is not None:
        out += _fpfn_summary(models + sources, suppressions, llm_idx)
    out += ["## Models", ""]
    for n in models:
        out += _model_section(n, suppressions, llm_idx)
    out += ["## Sources", ""]
    for n in sources:
        out += _model_section(n, suppressions, llm_idx)
    out += _judgement_section()
    return "\n".join(out)


def cmd(args: Namespace) -> int:
    sel = selection.from_args(args)
    files = selection.resolve_model_files(sel)
    in_scope = {str(f) for f in files}
    manifest = config.under_root(args.manifest)
    if manifest is None or not manifest.exists():
        raise FileNotFoundError(f"dbt manifest not found at '{manifest}'. Run `dbt parse` or pass --parse.")
    catalog = config.under_root(getattr(args, "catalog", None))
    nodes = load_node_facts(manifest, catalog if catalog and catalog.exists() else None)
    review = None
    review_path = config.under_root(getattr(args, "review", None))
    if review_path:
        if not Path(review_path).exists():
            raise FileNotFoundError(f"--review file not found: {review_path}")
        review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    md = build_markdown(nodes, in_scope, Suppressions.load(config.PROJECT_ROOT), selection.describe(sel), review)
    out = config.under_root(args.output) if getattr(args, "output", None) else None
    if out:
        Path(out).write_text(md, encoding="utf-8")
        log.info("wrote per-model taxonomy review to %s", out)
    else:
        print(md)
    return 0
