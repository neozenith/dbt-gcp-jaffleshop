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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import groupby
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


# ─── reconciliation records + categories ─────────────────────────────────────

# (node, code, det_token, evidence, llm_verdict, category)
_Record = tuple[NodeFacts, str, str, str, "str | None", str]
_BADGE = {"pass": "✅", "gap": "❌", "suppressed": "🟡", "n/a": "—", "no-detector": "—"}


def _category(det: str, llm: str | None) -> str:
    if det == "pass" and llm == "gap":
        return "fp"  # false positive — LLM flagged a covered rule
    if det == "gap" and llm == "present":
        return "fn"  # false negative — LLM claimed a real gap was covered
    if det == "gap" and llm in (None, "n/a"):
        return "missed"  # real gap the LLM did not raise
    if det == "n/a" and llm in ("present", "gap"):
        return "appl"  # applicability — detector can't decide
    if det == "suppressed" and llm in ("present", "gap"):
        return "supp"
    if det == "no-detector" and llm == "gap":
        return "unverified"  # LLM-only finding
    return "agree"


def _records(nodes: list[NodeFacts], suppressions: Suppressions, llm_idx: dict[str, dict[str, str]]) -> list[_Record]:
    recs: list[_Record] = []
    for n in nodes:
        llm = llm_idx.get(n.name, {})
        for code in dict.fromkeys(list(DETECTORS) + list(llm)):
            det, ev = _det_verdict(n, code, suppressions)
            llm_v = llm.get(code)
            recs.append((n, code, det, ev, llm_v, _category(det, llm_v)))
    return recs


def _rule_title(code: str) -> str:
    return (get_rule(code) or {}).get("title", code)


def _names(recs: list[_Record]) -> str:
    return ", ".join(f"`{r[0].name}`" for r in recs)


# ─── narrative sections ───────────────────────────────────────────────────────


def _glance(models: list, sources: list, recs: list[_Record], review: dict | None, has_catalog: bool) -> list[str]:
    c = Counter(r[5] for r in recs)
    det_gaps = sum(1 for r in recs if r[2] == "gap")
    usage = (review or {}).get("usage", {})
    return [
        "## At a glance",
        "",
        f"Deterministic detectors evaluated **{len(DETECTORS)} rules** across **{len(models)} models** and "
        f"**{len(sources)} sources** (columns {'warehouse-resolved' if has_catalog else 'YAML-declared'}), "
        f"reconciled against the LLM review ({usage.get('calls', '?')} calls, {usage.get('total_tokens', '?')} tokens). "
        "The disagreements to review:",
        "",
        f"- 🔴 **{c['fp']} false positives** — the LLM flagged a gap a test already covers",
        f"- 🔴 **{c['fn'] + c['missed']} false negatives** — a real gap the LLM marked covered or never raised",
        f"- 🟠 **{c['appl']} applicability calls** — the detector can't decide; you adjudicate",
        f"- ⚪ **{c['unverified']} LLM-only findings** — no deterministic check exists",
        f"- 🟡 **{c['supp']} suppressed-but-flagged** · ✅ **{c['agree']} agreements**",
        "",
        f"> Independently of the LLM, the deterministic checks found **{det_gaps} real gaps** — the actual to-do list.",
        "",
    ]


def _decisions(recs: list[_Record]) -> list[str]:
    by: dict[str, list[_Record]] = defaultdict(list)
    for r in recs:
        by[r[5]].append(r)
    out = ["## Decisions to make", ""]

    out += ["### 🔴 False negatives — a real gap the LLM did **not** flag", ""]
    fn = sorted(by["fn"] + by["missed"], key=lambda r: (r[1], r[0].name))
    if not fn:
        out += ["_None — the LLM raised every gap the detectors found._", ""]
    for code, g in groupby(fn, key=lambda r: r[1]):
        grp = list(g)
        active = [r for r in grp if r[4] == "present"]
        ev = f" ({grp[0][3]})" if len(grp) == 1 and grp[0][3] else ""
        tail = f" — _LLM marked present on {_names(active)}_" if active else " — _LLM never raised it_"
        out.append(f"- **`{code}` {_rule_title(code)}** on {_names(grp)}{ev}.{tail}")
    out.append("")

    out += ["### 🔴 False positives — the LLM flagged a gap a test already covers", ""]
    fp = sorted(by["fp"], key=lambda r: (r[1], r[0].name))
    if not fp:
        out += ["_None._", ""]
    for code, g in groupby(fp, key=lambda r: r[1]):
        grp = list(g)
        out.append(f"- **`{code}` {_rule_title(code)}** — a test exists on {_names(grp)}, but the LLM flagged it missing.")
    out.append("")

    out += ["### 🟠 Applicability — the detector can't decide; you adjudicate", ""]
    ap = sorted(by["appl"], key=lambda r: (r[1], r[0].name))
    if not ap:
        out += ["_None._", ""]
    for code, g in groupby(ap, key=lambda r: r[1]):
        grp = list(g)
        out.append(f"- **`{code}` {_rule_title(code)}** on {_names(grp)} — deterministic n/a (see caveats); LLM asserts it applies.")
    out.append("")

    out += ["### ⚪ LLM-only findings — no deterministic check (judgement call)", ""]
    unv: dict[str, list[str]] = defaultdict(list)
    for r in by["unverified"]:
        unv[r[0].name].append(r[1])
    if not unv:
        out += ["_None._", ""]
    for m in sorted(unv):
        out.append(f"- `{m}` — {', '.join(f'`{c}`' for c in sorted(unv[m]))}")
    out.append("")

    if by["supp"]:
        out += ["### 🟡 Suppressed but LLM-flagged", ""]
        out += [f"- `{r[0].name}` · `{r[1]}` — suppressed in `adaf.yml`, but the LLM still raised it." for r in by["supp"]]
        out.append("")
    return out


def _status_badges(n: NodeFacts, suppressions: Suppressions) -> str:
    if n.resource_type != "model":
        return f"**freshness** {'✅' if n.has_freshness else '❌'}"
    parts = [f"**grain** {_BADGE[_det_verdict(n, 'MD-01', suppressions)[0]]}"]
    md02 = _det_verdict(n, "MD-02", suppressions)[0]
    if md02 != "n/a":
        parts.append(f"**contract** {_BADGE[md02]}")
    declared = len(n.columns)
    parts.append(f"{len(n.effective_columns())} cols ({declared} documented{' ⚠️' if declared == 0 else ''})")
    return " · ".join(parts)


def _model_block(n: NodeFacts, suppressions: Suppressions, llm_idx: dict[str, dict[str, str]] | None) -> list[str]:
    out = [f"### `{n.name}` · {n.resource_type}" + (f" · `{n.layer}`" if n.layer else ""), "", _status_badges(n, suppressions), ""]

    gaps = [f"`{code}` {ev}" for code in DETECTORS for det, ev in [_det_verdict(n, code, suppressions)] if det == "gap"]
    if gaps:
        out += ["**Gaps:** " + " · ".join(gaps), ""]

    if llm_idx is not None:
        llm = llm_idx.get(n.name, {})
        mark = {"fp": "🔴 FP", "fn": "🔴 FN", "missed": "🔴 FN", "appl": "🟠", "supp": "🟡"}
        diss = [
            f"{mark[cat]} `{code}`"
            for code in dict.fromkeys(list(DETECTORS) + list(llm))
            for cat in [_category(_det_verdict(n, code, suppressions)[0], llm.get(code))]
            if cat in mark
        ]
        if diss:
            out += ["**LLM disagreements:** " + " · ".join(diss), ""]

    # Exhaustive evidence, tucked away.
    out += ["<details><summary>facts · all rules · LLM reconciliation</summary>", ""]
    out += _facts_block(n)
    out += [
        "",
        "| Rule | Applies? | Verdict | Evidence (fact) | Detector |",
        "|---|---|---|---|---|",
    ]
    for code in DETECTORS:
        det, ev = _det_verdict(n, code, suppressions)
        if det == "suppressed":
            ev = f"{ev} — suppressed: {suppressions.reason_for(code, n.original_file_path)}"
        out.append(f"| `{code}` | {'no' if det == 'n/a' else 'yes'} | {_det_display(det, get_rule(code) or {})} "
                   f"| {ev or '—'} | `{DETECTORS[code].__name__}` |")
    if llm_idx is not None:
        out += [
            "",
            "_LLM reconciliation:_",
            "",
            "| Rule | Deterministic | LLM | Assessment |",
            "|---|---|---|---|",
            *[row for _r, row in _reconcile_rows(n, suppressions, llm_idx.get(n.name, {}))],
        ]
    out += ["", "</details>", ""]
    return out


def _appendix() -> list[str]:
    out = [
        "## Appendix",
        "",
        "<details><summary><b>Detector caveats — how to read a 🔴 / 🟠</b></summary>",
        "",
        "The detectors are deterministic but heuristic about *which column plays which role*:",
        "",
        "- **MD-01** counts a model-level `unique` **or** `dbt_utils.unique_combination_of_columns` as a grain test. "
        "So an MD-01 false positive means *a uniqueness test exists* — if the LLM wanted an explicit "
        "`unique_combination_of_columns`, that is a stricter style, not a hallucinated fact.",
        "- **EN-01** infers the PK as `<model>_id` or the **sole** `*_id`/`*_uuid` column; a model with several key "
        "columns yields *no identifiable PK* → n/a (a detector limit, hence 🟠 — not an LLM error).",
        "- **EN-03** treats every non-PK `*_id`/`*_uuid` as a FK needing `relationships`; it may over-include a key "
        "when the PK isn't identified.",
        "- **TM-SC-03** needs `catalog.json` (a build) to see column types; without it, n/a.",
        "- Columns are warehouse-resolved from `catalog.json` when present, else YAML-declared.",
        "",
        "</details>",
        "",
        "<details><summary><b>Rules with no deterministic detector (LLM-judgement only)</b></summary>",
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
    return out + ["", "</details>", ""]


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
    usage = (review or {}).get("usage", {})

    prov = (
        f"Catalogue `v{cat['version']}` ({len(cat['rules'])} rules) · {len(DETECTORS)} deterministic detectors · "
        f"scope: {scope} · columns {'warehouse-resolved' if has_catalog else 'YAML-declared'}"
    )
    if llm_idx is not None:
        prov += f" · LLM `adaf review` {usage.get('calls', '?')} calls / {usage.get('total_tokens', '?')} tok"
    prov += f" · generated {ts}"

    out = [
        "# Testing-taxonomy review — dbt-jaffleshop",
        "",
        "Where the LLM taxonomy review (`adaf review`) agrees and disagrees with the deterministic checks "
        "(`adaf check taxonomy`). The deterministic verdicts are generated by detectors over the dbt manifest + "
        "catalog — **not hand-authored** — so the disagreements below are the real false-positive / false-negative "
        "surface to review. Every per-model `<details>` carries the full lineage (rule → detector → fact).",
        "",
        f"_{prov}_",
        "",
    ]
    if llm_idx is None:
        out += [
            "> No `--review` was supplied: this run shows deterministic findings only. Pass "
            "`--review <adaf review --json>` for the false-positive / false-negative view.",
            "",
        ]
        recs: list[_Record] = []
    else:
        recs = _records(models + sources, suppressions, llm_idx)
        out += _glance(models, sources, recs, review, has_catalog)
        out += _decisions(recs)

    out += ["## Per model", ""]
    for n in models:
        out += _model_block(n, suppressions, llm_idx)
    out += ["## Sources", ""]
    for n in sources:
        out += _model_block(n, suppressions, llm_idx)
    out += _appendix()
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
