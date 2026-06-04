#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Testing-taxonomy review for a PR's dbt models, posted as several comment variants.

Runs the `testing-taxonomy-review` skill's decision framework over dbt models using
GitHub Models (keyless via GITHUB_TOKEN) to emit findings conforming to
review-output.schema.json, then upserts FOUR sticky PR comments so the output formats
can be compared:

  1. matrix-changed  — rows = models changed in the PR, columns = applicable rule codes,
                       cells = ✅ present / ❌ missing / ➖ n/a.
  2. fails-changed   — same shape, narrowed to rules that APPLY and FAIL somewhere
                       (only failing rule codes as columns, only models with a failure as rows).
  3. matrix-all      — variant 1 over ALL models in the project.
  4. fails-all       — variant 2 over ALL models in the project.

Each variant has its own HTML-comment marker so it updates in place on re-run.

Stdlib-only on purpose: runs with `uv run --no-project` on a GitHub runner with no
external LLM SDK and no vendor API key — GitHub Models inference is reached with the
workflow's GITHUB_TOKEN (permissions: models: read).

Env (set by the workflow):
  GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER, BASE_SHA, HEAD_SHA
  MODEL            GitHub Models model id (default openai/gpt-4o)
  MODELS_ENDPOINT  inference endpoint (default https://models.github.ai/inference)
  MODELS_GLOB      dbt models path prefix (default dbt-jaffleshop/models)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
RULES = json.loads((SKILL_DIR / "rules.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((SKILL_DIR / "review-output.schema.json").read_text(encoding="utf-8"))
CODE_ORDER = [r["code"] for r in RULES["rules"]]
TITLE_BY_CODE = {r["code"]: r["title"] for r in RULES["rules"]}

STATUS_EMOJI = {"applicable_present": "✅", "applicable_missing": "❌", "not_applicable": "➖"}

# One marker per variant so each is upserted independently.
MARKERS = {
    "matrix_changed": "<!-- ttr:matrix-changed -->",
    "matrix_all": "<!-- ttr:matrix-all -->",
}
# Markers from variants we no longer post; any lingering comments are deleted on each run.
RETIRED_MARKERS = ["<!-- ttr:fails-changed -->", "<!-- ttr:fails-all -->"]
LEGEND = "✅ present · ❌ missing (gap) · ➖ n/a"
FOOTER = "<sub>Rule codes: [`rules.json`](.github/actions/dbt-testing-taxonomy-review/rules.json) · vignettes in `docs/guides/testing_taxonomy/`.</sub>"


def env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None:
        sys.exit(f"error: required env var {name} is not set")
    return val


def changed_models(base: str, head: str, glob_prefix: str) -> list[Path]:
    """Added/Modified .sql files under the models path between base and head."""
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AM", base, head,
         "--", f"{glob_prefix}/**/*.sql", f"{glob_prefix}/*.sql"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [Path(p) for p in out.splitlines() if p.strip()]


def all_models(glob_prefix: str) -> list[Path]:
    """Every .sql model in the project (for the project-wide variants)."""
    return sorted(Path(glob_prefix).rglob("*.sql"))


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


def build_catalogue() -> str:
    lines = []
    for r in RULES["rules"]:
        sub = f" ({r['sub_role']})" if r.get("sub_role") else ""
        lines.append(
            f"- {r['code']} [{r['role']}{sub}; {'/'.join(r['wang_strong'])}; {r['cost_class']}] "
            f"{r['title']}: {r['summary']} APPLIES WHEN: {r['applies_when']}"
        )
    return "\n".join(lines)


def system_prompt() -> str:
    codes = ", ".join(CODE_ORDER)
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


def model_block(sql: Path) -> str:
    return (f"### MODEL: {sql.stem}\nFILE: {sql}\n\n--- SQL ---\n{sql.read_text(encoding='utf-8')}\n\n"
            f"--- YAML (existing tests/contract) ---\n{sibling_yaml(sql) or '(no schema yml found)'}\n")


def user_prompt(models: list[Path]) -> str:
    return (
        "Review the following dbt models. For each, emit a finding for EVERY rule you "
        "evaluated — applicable_present, applicable_missing, AND not_applicable — so a full "
        "coverage matrix can be built. Emit schema-conforming JSON.\n\n"
        + "\n".join(model_block(sql) for sql in models)
    )


def est_tokens(text: str) -> int:
    """Conservative token estimate (~3 chars/token, over-counting on purpose) for batching."""
    return len(text) // 3 + 1


# Stay comfortably under GitHub Models' ~8000-token request cap (system prompt + the
# response_format schema + the model blocks all count as input).
REQUEST_TOKEN_CAP = 7000


def batch_models(models: list[Path], budget_tokens: int = 5000) -> list[list[Path]]:
    """Pack models into batches whose combined size stays under budget_tokens, so each
    request (system prompt ~1.6k + batch) stays under GitHub Models' ~8000-token cap while
    making far fewer requests than one-per-model (which trips the free-tier rate limit)."""
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


def response_format() -> dict:
    schema = json.loads(json.dumps(SCHEMA))  # deep copy
    (schema["properties"]["models"]["items"]["properties"]["findings"]["items"]
        ["properties"]["rule_code"]["enum"]) = CODE_ORDER
    for k in ("$schema", "title", "description"):
        schema.pop(k, None)
    return {"type": "json_schema",
            "json_schema": {"name": "testing_taxonomy_review", "strict": True, "schema": schema}}


def call_model(endpoint: str, token: str, model: str, sys_p: str, usr_p: str) -> tuple[dict, dict]:
    """Return (parsed_content, usage). usage = {prompt_tokens, completion_tokens, total_tokens}."""
    with_temp = True  # gpt-5/o-series reject temperature != default; drop it if rejected.

    def _body() -> bytes:
        payload: dict = {
            "model": model,
            "messages": [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
            "response_format": response_format(),
        }
        if with_temp:
            payload["temperature"] = 0
        return json.dumps(payload).encode("utf-8")

    # GitHub Models free tier rate-limits requests; back off on 429 (honour Retry-After).
    attempts = 6
    for attempt in range(attempts):
        req = urllib.request.Request(
            f"{endpoint.rstrip('/')}/chat/completions", data=_body(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "Accept": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            content = json.loads(payload["choices"][0]["message"]["content"])
            return content, (payload.get("usage") or {})
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code == 429 and attempt < attempts - 1:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                wait = int(retry_after) if (retry_after and retry_after.isdigit()) else min(60, 10 * (2 ** attempt))
                print(f"  rate-limited (429); retrying in {wait}s (attempt {attempt + 1}/{attempts})")
                time.sleep(wait)
                continue
            if e.code == 400 and with_temp and "temperature" in detail.lower():
                print("  model rejects temperature=0; retrying with model default")
                with_temp = False
                continue
            sys.exit(f"error: GitHub Models call failed ({e.code}): {detail}")
    sys.exit("error: GitHub Models call failed after retries")


def validate(result: dict) -> None:
    valid = {r["code"] for r in RULES["rules"]}
    if "models" not in result or not isinstance(result["models"], list):
        sys.exit("error: model output missing 'models' array")
    for m in result["models"]:
        for f in m.get("findings", []):
            if f.get("rule_code") not in valid:
                sys.exit(f"error: model emitted unknown rule_code {f.get('rule_code')!r}")


def review_models(endpoint: str, token: str, model: str, models: list[Path]) -> tuple[dict, dict]:
    """Review each model in its OWN request — GitHub Models caps a request at ~8000 input
    tokens, so batching the whole project overflows. One model + the catalogue fits easily.
    Returns (merged_results, usage_totals) where usage_totals sums token usage across calls."""
    merged: dict = {"models": []}
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
    sys_p = system_prompt()
    # Reserve room for the fixed per-request overhead (system prompt + the JSON schema that
    # response_format sends) so a batch's model blocks can't push the request over the cap.
    overhead = est_tokens(sys_p) + est_tokens(json.dumps(response_format()))
    budget = max(1500, REQUEST_TOKEN_CAP - overhead)
    batches = batch_models(models, budget)
    print(f"  overhead≈{overhead} tok · per-request model budget≈{budget} tok · {len(batches)} batch(es)")
    for i, batch in enumerate(batches):
        names = ", ".join(s.stem for s in batch)
        print(f"  [batch {i + 1}/{len(batches)}] {len(batch)} model(s): {names}")
        result, usage = call_model(endpoint, token, model, sys_p, user_prompt(batch))
        validate(result)
        merged["models"].extend(result.get("models", []))
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            totals[k] += int(usage.get(k, 0) or 0)
        totals["calls"] += 1
        print(f"      tokens: in={usage.get('prompt_tokens', 0)} out={usage.get('completion_tokens', 0)}")
        if i + 1 < len(batches):
            time.sleep(5)  # courtesy spacing for the free-tier per-minute limit
    return merged, totals


# --- renderers ---------------------------------------------------------------

def _index(result: dict) -> dict[str, dict[str, str]]:
    """{model_name: {rule_code: status}}"""
    return {m["model"]: {f["rule_code"]: f["status"] for f in m.get("findings", [])}
            for m in result.get("models", [])}


def matrix_comment(result: dict, marker: str, scope: str) -> str:
    idx = _index(result)
    head = [marker, f"## 🧪 Taxonomy coverage matrix — {scope}", ""]
    if not idx:
        return "\n".join(head + ["_No models to review._"])
    applicable = {c for codes in idx.values() for c, s in codes.items()
                  if s in ("applicable_present", "applicable_missing")}
    cols = [c for c in CODE_ORDER if c in applicable]
    if not cols:
        return "\n".join(head + ["_No applicable rules._"])
    header = "| Model / Rule | " + " | ".join(cols) + " |"
    sep = "|:---|" + "|".join([":---:"] * len(cols)) + "|"
    rows = [f"| `{m}` | " + " | ".join(STATUS_EMOJI.get(idx[m].get(c) or "", "➖") for c in cols) + " |"
            for m in sorted(idx)]
    return "\n".join(head + [f"Rows = models · columns = applicable rule codes · {LEGEND}", "",
                             header, sep, *rows, "", FOOTER])


# --- GitHub API --------------------------------------------------------------

def api(method: str, url: str, token: str, data: dict | None = None):
    req = urllib.request.Request(
        url, method=method,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def upsert_comment(repo: str, pr: str, token: str, marker: str, body: str) -> None:
    base = f"https://api.github.com/repos/{repo}"
    existing = api("GET", f"{base}/issues/{pr}/comments?per_page=100", token)
    mine = next((c for c in existing if marker in c.get("body", "")), None)
    if mine:
        api("PATCH", f"{base}/issues/comments/{mine['id']}", token, {"body": body})
        print(f"  updated comment {mine['id']} ({marker})")
    else:
        api("POST", f"{base}/issues/{pr}/comments", token, {"body": body})
        print(f"  created comment ({marker})")


def delete_retired_comments(repo: str, pr: str, token: str) -> None:
    """Remove comments from variants we no longer post (keeps the PR tidy after a trim)."""
    base = f"https://api.github.com/repos/{repo}"
    for c in api("GET", f"{base}/issues/{pr}/comments?per_page=100", token):
        if any(m in c.get("body", "") for m in RETIRED_MARKERS):
            api("DELETE", f"{base}/issues/comments/{c['id']}", token)
            print(f"  deleted retired comment {c['id']}")


def estimated_cost(totals: dict, in_price: float, out_price: float) -> float:
    return totals["prompt_tokens"] / 1e6 * in_price + totals["completion_tokens"] / 1e6 * out_price


def usage_footer(totals: dict, model: str, in_price: float, out_price: float) -> str:
    cost = estimated_cost(totals, in_price, out_price)
    return (f"<sub>🧮 {totals['calls']} `{model}` call(s) · "
            f"{totals['prompt_tokens']:,} input + {totals['completion_tokens']:,} output "
            f"({totals['total_tokens']:,} total) tokens · est. **~${cost:.4f}** at list price "
            f"(GitHub Models free tier may bill $0).</sub>")


def write_step_summary(totals: dict, model: str, in_price: float, out_price: float) -> None:
    """Append a usage block to the GHA run's job summary (and always echo to the log)."""
    cost = estimated_cost(totals, in_price, out_price)
    block = "\n".join([
        "## 🧮 testing-taxonomy review — token usage & cost", "",
        f"- **Model:** `{model}`", f"- **Calls:** {totals['calls']}",
        f"- **Input tokens:** {totals['prompt_tokens']:,}",
        f"- **Output tokens:** {totals['completion_tokens']:,}",
        f"- **Total tokens:** {totals['total_tokens']:,}",
        f"- **Estimated cost:** ~${cost:.4f} (at {model} list price ${in_price}/1M in, "
        f"${out_price}/1M out; GitHub Models free tier may bill $0).", "",
    ])
    print(block)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(block + "\n")


def main() -> None:
    token = env("GITHUB_TOKEN")
    repo = env("GITHUB_REPOSITORY")
    pr = env("PR_NUMBER")
    base, head = env("BASE_SHA"), env("HEAD_SHA")
    model = env("MODEL", "openai/gpt-4o")
    endpoint = env("MODELS_ENDPOINT", "https://models.github.ai/inference")
    glob_prefix = env("MODELS_GLOB", "dbt-jaffleshop/models")
    in_price = float(env("COST_PER_1M_INPUT", "2.5"))
    out_price = float(env("COST_PER_1M_OUTPUT", "10"))

    # Review every model once (per-model requests), then derive the changed subset by name.
    # Avoids reviewing changed models twice and keeps the "changed" and "all" matrices consistent.
    changed_names = {p.stem for p in changed_models(base, head, glob_prefix)}
    print(f"changed models: {', '.join(sorted(changed_names)) or '(none)'}")
    res_all, totals = review_models(endpoint, token, model, all_models(glob_prefix))
    res_changed = {"models": [m for m in res_all["models"] if m["model"] in changed_names]}

    # The whole run is the all-models pass; the same usage footer goes on every comment.
    footer = "\n\n" + usage_footer(totals, model, in_price, out_price)
    upsert_comment(repo, pr, token, MARKERS["matrix_changed"],
                   matrix_comment(res_changed, MARKERS["matrix_changed"], "changed models") + footer)
    upsert_comment(repo, pr, token, MARKERS["matrix_all"],
                   matrix_comment(res_all, MARKERS["matrix_all"], "all models") + footer)
    delete_retired_comments(repo, pr, token)

    write_step_summary(totals, model, in_price, out_price)


if __name__ == "__main__":
    main()
