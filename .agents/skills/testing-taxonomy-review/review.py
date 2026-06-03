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
    "fails_changed": "<!-- ttr:fails-changed -->",
    "matrix_all": "<!-- ttr:matrix-all -->",
    "fails_all": "<!-- ttr:fails-all -->",
}
LEGEND = "✅ present · ❌ missing (gap) · ➖ n/a"
FOOTER = "<sub>Rule codes: [`rules.json`](.agents/skills/testing-taxonomy-review/rules.json) · vignettes in `docs/guides/testing_taxonomy/`.</sub>"


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


def user_prompt(models: list[Path]) -> str:
    parts = []
    for sql in models:
        parts.append(
            f"### MODEL: {sql.stem}\nFILE: {sql}\n\n--- SQL ---\n{sql.read_text(encoding='utf-8')}\n\n"
            f"--- YAML (existing tests/contract) ---\n{sibling_yaml(sql) or '(no schema yml found)'}\n"
        )
    return (
        "Review the following dbt models. For each, emit a finding for EVERY rule you "
        "evaluated — applicable_present, applicable_missing, AND not_applicable — so a full "
        "coverage matrix can be built. Emit schema-conforming JSON.\n\n" + "\n".join(parts)
    )


def response_format() -> dict:
    schema = json.loads(json.dumps(SCHEMA))  # deep copy
    (schema["properties"]["models"]["items"]["properties"]["findings"]["items"]
        ["properties"]["rule_code"]["enum"]) = CODE_ORDER
    for k in ("$schema", "title", "description"):
        schema.pop(k, None)
    return {"type": "json_schema",
            "json_schema": {"name": "testing_taxonomy_review", "strict": True, "schema": schema}}


def call_model(endpoint: str, token: str, model: str, sys_p: str, usr_p: str) -> dict:
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "messages": [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
        "response_format": response_format(),
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{endpoint.rstrip('/')}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"error: GitHub Models call failed ({e.code}): {e.read().decode('utf-8', 'replace')}")
    return json.loads(payload["choices"][0]["message"]["content"])


def validate(result: dict) -> None:
    valid = {r["code"] for r in RULES["rules"]}
    if "models" not in result or not isinstance(result["models"], list):
        sys.exit("error: model output missing 'models' array")
    for m in result["models"]:
        for f in m.get("findings", []):
            if f.get("rule_code") not in valid:
                sys.exit(f"error: model emitted unknown rule_code {f.get('rule_code')!r}")


def review_set(endpoint: str, token: str, model: str, models: list[Path]) -> dict:
    if not models:
        return {"models": []}
    print(f"  reviewing {len(models)} model(s): {', '.join(m.stem for m in models)}")
    result = call_model(endpoint, token, model, system_prompt(), user_prompt(models))
    validate(result)
    return result


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


def failures_comment(result: dict, marker: str, scope: str) -> str:
    idx = _index(result)
    head = [marker, f"## 🧪 Taxonomy failures — {scope}", ""]
    if not idx:
        return "\n".join(head + ["_No models to review._"])
    failed = {c for codes in idx.values() for c, s in codes.items() if s == "applicable_missing"}
    cols = [c for c in CODE_ORDER if c in failed]
    fail_models = [m for m, codes in idx.items()
                   if any(s == "applicable_missing" for s in codes.values())]
    if not cols or not fail_models:
        return "\n".join(head + ["✅ No applicable rules are failing."])
    header = "| Model / Failed rule | " + " | ".join(cols) + " |"
    sep = "|:---|" + "|".join([":---:"] * len(cols)) + "|"
    rows = []
    for m in sorted(fail_models):
        cells = ["❌" if idx[m].get(c) == "applicable_missing"
                 else ("✅" if idx[m].get(c) == "applicable_present" else "")
                 for c in cols]
        rows.append(f"| `{m}` | " + " | ".join(cells) + " |")
    legend = "Only rules that **apply and fail** somewhere · ❌ missing · ✅ present (elsewhere) · blank n/a"
    return "\n".join(head + [legend, "", header, sep, *rows, "", FOOTER])


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


def main() -> None:
    token = env("GITHUB_TOKEN")
    repo = env("GITHUB_REPOSITORY")
    pr = env("PR_NUMBER")
    base, head = env("BASE_SHA"), env("HEAD_SHA")
    model = env("MODEL", "openai/gpt-4o")
    endpoint = env("MODELS_ENDPOINT", "https://models.github.ai/inference")
    glob_prefix = env("MODELS_GLOB", "dbt-jaffleshop/models")

    print("changed-model set:")
    res_changed = review_set(endpoint, token, model, changed_models(base, head, glob_prefix))
    print("all-model set:")
    res_all = review_set(endpoint, token, model, all_models(glob_prefix))

    upsert_comment(repo, pr, token, MARKERS["matrix_changed"],
                   matrix_comment(res_changed, MARKERS["matrix_changed"], "changed models"))
    upsert_comment(repo, pr, token, MARKERS["fails_changed"],
                   failures_comment(res_changed, MARKERS["fails_changed"], "changed models"))
    upsert_comment(repo, pr, token, MARKERS["matrix_all"],
                   matrix_comment(res_all, MARKERS["matrix_all"], "all models"))
    upsert_comment(repo, pr, token, MARKERS["fails_all"],
                   failures_comment(res_all, MARKERS["fails_all"], "all models"))


if __name__ == "__main__":
    main()
