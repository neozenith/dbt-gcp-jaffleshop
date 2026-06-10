"""``adaf review`` — LLM testing-taxonomy review of dbt models via GitHub Models.

Migrated from the standalone ``review.py`` engine. What changed in the move:

* the rule catalogue and the output schema come from ``adaf.rules`` (the SSoT), and the
  ``rule_code`` enum is injected from ``rule_codes()`` (``review_response_format``) so the
  LLM's allowed codes can't drift from the catalogue;
* the prompt's per-rule dimension tag is the model's **DAMA-UK6** ``dama`` (the operational
  lens), not the now-corrected ``wang_strong`` field;
* model selection reuses the shared ``selection``/``gitutil`` machinery, so ``review`` and
  ``check`` agree on "what changed";
* it is usable LOCALLY (default: review the changed models, print the matrix, ``--json`` for
  the dev skill) and in CI (``--post`` upserts the changed + all sticky comments + job summary).

Keyless: the only credential is ``GITHUB_TOKEN`` (env or ``--token``) with ``models: read``.
Uses ``urllib`` only for the HTTP calls — no vendor SDK, no API key.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from argparse import Namespace
from pathlib import Path

from adaf import config, gitutil
from adaf.dbt import selection
from adaf.rules import all_rules, review_response_format, rule_codes
from adaf.suppression import Suppressions

log = logging.getLogger(__name__)

STATUS_EMOJI = {"applicable_present": "✅", "applicable_missing": "❌", "not_applicable": "➖"}
MARKERS = {"matrix_changed": "<!-- ttr:matrix-changed -->", "matrix_all": "<!-- ttr:matrix-all -->"}
RETIRED_MARKERS = ["<!-- ttr:fails-changed -->", "<!-- ttr:fails-all -->"]
LEGEND = "✅ present · ❌ missing (gap) · ➖ n/a"
FOOTER = "<sub>Rule codes: `adaf rules` (catalogue) · vignettes in `docs/guides/testing_taxonomy/`.</sub>"

# Stay under GitHub Models' ~8000-token request cap (system prompt + the response_format schema
# + the model blocks all count as input).
REQUEST_TOKEN_CAP = 7000


# ─── prompt construction (catalogue-driven) ──────────────────────────────────


def build_catalogue() -> str:
    lines = []
    for r in all_rules():
        sub = f" ({r['sub_role']})" if r.get("sub_role") else ""
        # DAMA-UK6 is the operational dimension shown to the reviewer (was the mislabeled
        # wang_strong); the genuine Wang-Strong lens is secondary and omitted from the prompt.
        lines.append(
            f"- {r['code']} [{r['role']}{sub}; {'/'.join(r['dama'])}; {r['cost_class']}] "
            f"{r['title']}: {r['summary']} APPLIES WHEN: {r['applies_when']}"
        )
    return "\n".join(lines)


def system_prompt() -> str:
    codes = ", ".join(rule_codes())
    return (
        "You are a senior analytics engineer reviewing dbt models against this project's "
        "TESTING TAXONOMY. Decide, per model, which taxonomy rules APPLY (by each column's "
        "query role: JOIN key=entity EN-, GROUP BY axis=dimension DM-, aggregate=measure MS-, "
        "date/datetime=time TM-SC/GR/AU-, plus model-level MD-) and whether each applicable "
        "rule is already covered by an existing data_test in the model's YAML.\n\n"
        "HARD RULES:\n"
        "- MD-01 (grain test) applies to EVERY model; if absent it is a blocker.\n"
        "- A column plays MULTIPLE roles — union the suites; do not assign one role per column.\n"
        "- *-anomaly rules (DM-05/MS-05/MD-07) use Elementary, which is PROD-only here; treat as info unless already configured.\n"
        "- Only use rule codes from this set: " + codes + ".\n"
        "- status: applicable_present (a matching test exists), applicable_missing (gap), not_applicable.\n"
        "- severity applies to GAPS only: blocker (missing grain/contract/FK-integrity), warning (contained "
        "missing coverage), info. ALWAYS set severity=info for applicable_present (the rule is already satisfied) "
        "and for not_applicable.\n"
        "- Return ONLY JSON conforming to the provided schema. No prose.\n\n"
        "RULE CATALOGUE:\n" + build_catalogue()
    )


def sibling_yaml(sql_path: Path) -> str:
    """The model's own .yml schema (same stem), else any .yml in the dir naming it."""
    stem_yml = sql_path.with_suffix(".yml")
    if stem_yml.exists():
        return stem_yml.read_text(encoding="utf-8")
    hits = []
    for yml in sql_path.parent.glob("*.yml"):
        text = yml.read_text(encoding="utf-8")
        if sql_path.stem in text:
            hits.append(f"# from {yml.name}\n{text}")
    return "\n\n".join(hits)


def model_block(sql: Path) -> str:
    rel = sql.relative_to(config.PROJECT_ROOT) if sql.is_absolute() else sql
    return (
        f"### MODEL: {sql.stem}\nFILE: {rel}\n\n--- SQL ---\n{sql.read_text(encoding='utf-8')}\n\n"
        f"--- YAML (existing tests/contract) ---\n{sibling_yaml(sql) or '(no schema yml found)'}\n"
    )


def user_prompt(models: list[Path]) -> str:
    return (
        "Review the following dbt models. For each, emit a finding for EVERY rule you "
        "evaluated — applicable_present, applicable_missing, AND not_applicable — so a full "
        "coverage matrix can be built. Emit schema-conforming JSON.\n\n" + "\n".join(model_block(sql) for sql in models)
    )


def est_tokens(text: str) -> int:
    """Conservative token estimate (~3 chars/token, over-counting on purpose) for batching."""
    return len(text) // 3 + 1


def batch_models(models: list[Path], budget_tokens: int) -> list[list[Path]]:
    """Greedily pack models into batches under budget_tokens so each request stays below the cap."""
    batches: list[list[Path]] = []
    cur: list[Path] = []
    cur_tok = 0
    for sql in models:
        t = est_tokens(model_block(sql))
        if cur and cur_tok + t > budget_tokens:
            batches.append(cur)
            cur, cur_tok = [], 0
        cur.append(sql)
        cur_tok += t
    if cur:
        batches.append(cur)
    return batches


# ─── GitHub Models call ──────────────────────────────────────────────────────


def call_model(endpoint: str, token: str, model: str, sys_p: str, usr_p: str) -> tuple[dict, dict]:
    """Return (parsed_content, usage). Backs off on 429; drops temperature if the model rejects it."""
    with_temp = True  # gpt-5/o-series reject temperature != default; drop it if rejected.

    def _body() -> bytes:
        payload: dict = {
            "model": model,
            "messages": [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
            "response_format": review_response_format(),
        }
        if with_temp:
            payload["temperature"] = 0
        return json.dumps(payload).encode("utf-8")

    attempts = 6
    for attempt in range(attempts):
        req = urllib.request.Request(
            f"{endpoint.rstrip('/')}/chat/completions",
            data=_body(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            content = json.loads(payload["choices"][0]["message"]["content"])
            return content, (payload.get("usage") or {})
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code == 429 and attempt < attempts - 1:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                wait = int(retry_after) if (retry_after and retry_after.isdigit()) else min(60, 10 * (2**attempt))
                log.info("  rate-limited (429); retrying in %ds (attempt %d/%d)", wait, attempt + 1, attempts)
                time.sleep(wait)
                continue
            if e.code == 400 and with_temp and "temperature" in detail.lower():
                log.info("  model rejects temperature=0; retrying with model default")
                with_temp = False
                continue
            raise RuntimeError(f"GitHub Models call failed ({e.code}): {detail}") from e
    raise RuntimeError("GitHub Models call failed after retries")


def _validate_result(result: dict) -> None:
    valid = set(rule_codes())
    if "models" not in result or not isinstance(result["models"], list):
        raise RuntimeError("model output missing 'models' array")
    for m in result["models"]:
        for f in m.get("findings", []):
            if f.get("rule_code") not in valid:
                raise RuntimeError(f"model emitted unknown rule_code {f.get('rule_code')!r}")


def review_models(endpoint: str, token: str, model: str, models: list[Path]) -> tuple[dict, dict]:
    """Review all given models (batched under the token cap); merge findings + sum token usage."""
    merged: dict = {"models": []}
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
    if not models:
        return merged, totals
    sys_p = system_prompt()
    overhead = est_tokens(sys_p) + est_tokens(json.dumps(review_response_format()))
    budget = max(1500, REQUEST_TOKEN_CAP - overhead)
    batches = batch_models(models, budget)
    log.info("  overhead≈%d tok · per-request model budget≈%d tok · %d batch(es)", overhead, budget, len(batches))
    for i, batch in enumerate(batches):
        log.info("  [batch %d/%d] %d model(s): %s", i + 1, len(batches), len(batch), ", ".join(s.stem for s in batch))
        result, usage = call_model(endpoint, token, model, sys_p, user_prompt(batch))
        _validate_result(result)
        merged["models"].extend(result.get("models", []))
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            totals[k] += int(usage.get(k, 0) or 0)
        totals["calls"] += 1
        log.info("      tokens: in=%s out=%s", usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        if i + 1 < len(batches):
            time.sleep(5)  # courtesy spacing for the free-tier per-minute limit
    return merged, totals


# ─── rendering ───────────────────────────────────────────────────────────────


def apply_suppressions(result: dict, name_to_path: dict[str, str], suppressions: Suppressions) -> int:
    """Demote suppressed gaps (applicable_missing → not_applicable) so the matrix won't flag a rule
    the project has explicitly opted out of (adaf.yml glob or inline ``-- adaf-disable``). Returns the
    count demoted. Mirrors the deterministic checks: a suppressed rule never shows as a gap."""
    demoted = 0
    for m in result.get("models", []):
        rel = name_to_path.get(m.get("model", ""))
        if not rel:
            continue
        for f in m.get("findings", []):
            if f.get("status") == "applicable_missing" and suppressions.is_suppressed(f.get("rule_code", ""), rel):
                f["status"] = "not_applicable"
                demoted += 1
    return demoted


def _index(result: dict) -> dict[str, dict[str, str]]:
    """{model_name: {rule_code: status}}"""
    return {m["model"]: {f["rule_code"]: f["status"] for f in m.get("findings", [])} for m in result.get("models", [])}


def matrix_table(result: dict, scope: str) -> list[str]:
    """The coverage-matrix markdown lines (no HTML marker / footer): rows=models, cols=applicable codes."""
    idx = _index(result)
    head = [f"## 🧪 Taxonomy coverage matrix — {scope}", ""]
    if not idx:
        return head + ["_No models to review._"]
    applicable = {
        c for codes in idx.values() for c, s in codes.items() if s in ("applicable_present", "applicable_missing")
    }
    cols = [c for c in rule_codes() if c in applicable]
    if not cols:
        return head + ["_No applicable rules._"]
    header = "| Model / Rule | " + " | ".join(cols) + " |"
    sep = "|:---|" + "|".join([":---:"] * len(cols)) + "|"
    rows = [
        f"| `{m}` | " + " | ".join(STATUS_EMOJI.get(idx[m].get(c) or "", "➖") for c in cols) + " |"
        for m in sorted(idx)
    ]
    return head + [f"Rows = models · columns = applicable rule codes · {LEGEND}", "", header, sep, *rows]


def matrix_comment(result: dict, marker: str, scope: str) -> str:
    return "\n".join([marker, *matrix_table(result, scope), "", FOOTER])


# ─── GitHub API (only used by --post) ────────────────────────────────────────


def _api(method: str, url: str, token: str, data: dict | None = None):
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def upsert_comment(repo: str, pr: str, token: str, marker: str, body: str) -> None:
    base = f"https://api.github.com/repos/{repo}"
    existing = _api("GET", f"{base}/issues/{pr}/comments?per_page=100", token)
    mine = next((c for c in existing if marker in c.get("body", "")), None)
    if mine:
        _api("PATCH", f"{base}/issues/comments/{mine['id']}", token, {"body": body})
        log.info("  updated comment %s (%s)", mine["id"], marker)
    else:
        _api("POST", f"{base}/issues/{pr}/comments", token, {"body": body})
        log.info("  created comment (%s)", marker)


def delete_retired_comments(repo: str, pr: str, token: str) -> None:
    base = f"https://api.github.com/repos/{repo}"
    for c in _api("GET", f"{base}/issues/{pr}/comments?per_page=100", token):
        if any(m in c.get("body", "") for m in RETIRED_MARKERS):
            _api("DELETE", f"{base}/issues/comments/{c['id']}", token)
            log.info("  deleted retired comment %s", c["id"])


# ─── cost / usage ────────────────────────────────────────────────────────────


def estimated_cost(totals: dict, in_price: float, out_price: float) -> float:
    return totals["prompt_tokens"] / 1e6 * in_price + totals["completion_tokens"] / 1e6 * out_price


def usage_footer(totals: dict, model: str, in_price: float, out_price: float) -> str:
    cost = estimated_cost(totals, in_price, out_price)
    return (
        f"<sub>🧮 {totals['calls']} `{model}` call(s) · "
        f"{totals['prompt_tokens']:,} input + {totals['completion_tokens']:,} output "
        f"({totals['total_tokens']:,} total) tokens · est. **~${cost:.4f}** at list price "
        f"(GitHub Models free tier may bill $0).</sub>"
    )


def write_step_summary(totals: dict, model: str, in_price: float, out_price: float) -> None:
    cost = estimated_cost(totals, in_price, out_price)
    block = "\n".join(
        [
            "## 🧮 testing-taxonomy review — token usage & cost",
            "",
            f"- **Model:** `{model}`",
            f"- **Calls:** {totals['calls']}",
            f"- **Input tokens:** {totals['prompt_tokens']:,}",
            f"- **Output tokens:** {totals['completion_tokens']:,}",
            f"- **Total tokens:** {totals['total_tokens']:,}",
            f"- **Estimated cost:** ~${cost:.4f} (at {model} list price ${in_price}/1M in, "
            f"${out_price}/1M out; GitHub Models free tier may bill $0).",
            "",
        ]
    )
    log.info("%s", block)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).open("a", encoding="utf-8").write(block + "\n")


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"--post needs ${name} (the PR context), which is not set")
    return val


# ─── handler ─────────────────────────────────────────────────────────────────


def cmd_review(args: Namespace) -> int:
    token = getattr(args, "token", None) or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set (needed for keyless GitHub Models inference); pass --token.")

    all_paths = [config.PROJECT_ROOT / p for p in selection.all_model_files(config.PROJECT_ROOT)]
    changed_names = {p.stem for p in gitutil.changed_model_files(args.base_ref)}

    # Review ALL models when posting (both matrices come from one pass) or when --all; otherwise
    # only the changed subset — efficient for local / skill use.
    review_all = args.post or args.all_models
    review_paths = all_paths if review_all else [p for p in all_paths if p.stem in changed_names]

    if not review_paths:
        log.info("no models to review (scope=%s)", "all" if review_all else f"changed vs {args.base_ref}")
        if args.as_json:
            print(json.dumps({"usage": {}, "result": {"models": []}}, indent=2))
        return 0

    res, totals = review_models(args.endpoint, token, args.model, review_paths)

    # Honour the same suppressions the deterministic checks use: a rule the project opted out of
    # (adaf.yml / inline -- adaf-disable) must not resurface as an LLM-flagged gap.
    name_to_path = {p.stem: str(p.relative_to(config.PROJECT_ROOT)) for p in review_paths}
    demoted = apply_suppressions(res, name_to_path, Suppressions.load(config.PROJECT_ROOT))
    if demoted:
        log.info("  %d finding(s) demoted by suppressions (adaf.yml / -- adaf-disable)", demoted)

    display = res if args.all_models else {"models": [m for m in res["models"] if m["model"] in changed_names]}

    if args.as_json:
        print(json.dumps({"usage": totals, "result": display}, indent=2))
    else:
        scope = "all models" if args.all_models else f"changed models vs {args.base_ref}"
        for line in matrix_table(display, scope):
            log.info("%s", line)
        log.info("%s", usage_footer(totals, args.model, args.cost_in, args.cost_out))

    if args.post:
        repo, pr = _require_env("GITHUB_REPOSITORY"), _require_env("PR_NUMBER")
        footer = "\n\n" + usage_footer(totals, args.model, args.cost_in, args.cost_out)
        res_changed = {"models": [m for m in res["models"] if m["model"] in changed_names]}
        upsert_comment(
            repo,
            pr,
            token,
            MARKERS["matrix_changed"],
            matrix_comment(res_changed, MARKERS["matrix_changed"], "changed models") + footer,
        )
        upsert_comment(
            repo, pr, token, MARKERS["matrix_all"], matrix_comment(res, MARKERS["matrix_all"], "all models") + footer
        )
        delete_retired_comments(repo, pr, token)
        write_step_summary(totals, args.model, args.cost_in, args.cost_out)

    return 0
