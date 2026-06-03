#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Testing-taxonomy review for a PR's changed dbt models.

Runs the `testing-taxonomy-review` skill's decision framework over the dbt models
added/modified in a pull request, using GitHub Models (keyless via GITHUB_TOKEN) to
emit findings that conform to review-output.schema.json, then upserts a single sticky
PR comment with a tabular summary.

Stdlib-only on purpose: runs with `uv run --no-project` on a GitHub runner with no
external LLM SDK, no vendor API key — the GitHub subscription's Models inference is
reached with the workflow's GITHUB_TOKEN (permissions: models: read).

Env (all set by the workflow):
  GITHUB_TOKEN         runner token (models:read + pull-requests:write)
  GITHUB_REPOSITORY    owner/repo
  PR_NUMBER            pull request number
  BASE_SHA, HEAD_SHA   diff endpoints
  MODEL                GitHub Models model id (default openai/gpt-4o)
  MODELS_ENDPOINT      inference endpoint (default https://models.github.ai/inference)
  MODELS_GLOB          path prefix for dbt models (default dbt-jaffleshop/models)
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

COMMENT_MARKER = "<!-- testing-taxonomy-review -->"
VERDICT_BADGE = {"pass": "✅ pass", "gaps": "🟡 gaps", "blocker": "🔴 blocker"}
SEVERITY_RANK = {"blocker": 0, "warning": 1, "info": 2}
SEVERITY_BADGE = {"blocker": "🔴 blocker", "warning": "🟡 warning", "info": "ℹ️ info"}


def env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None:
        sys.exit(f"error: required env var {name} is not set")
    return val


def changed_models(base: str, head: str, glob_prefix: str) -> list[Path]:
    """Added/Modified .sql files under the models path between base and head."""
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AM", f"{base}", f"{head}",
         "--", f"{glob_prefix}/**/*.sql", f"{glob_prefix}/*.sql"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [Path(p) for p in out.splitlines() if p.strip()]


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
    codes = ", ".join(r["code"] for r in RULES["rules"])
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
        "- severity: blocker (grain/contract/FK integrity gaps), warning (contained coverage gap), info.\n"
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
        "Review the following changed dbt models. For each, list findings for every "
        "applicable rule (present and missing). Emit schema-conforming JSON.\n\n"
        + "\n".join(parts)
    )


def response_format() -> dict:
    """json_schema response format; enum injected from rules.json so it can't drift."""
    schema = json.loads(json.dumps(SCHEMA))  # deep copy
    codes = [r["code"] for r in RULES["rules"]]
    (schema["properties"]["models"]["items"]["properties"]["findings"]["items"]
        ["properties"]["rule_code"]["enum"]) = codes
    # GitHub Models / OpenAI strict mode rejects unknown top-level keywords.
    for k in ("$schema", "title", "description"):
        schema.pop(k, None)
    return {
        "type": "json_schema",
        "json_schema": {"name": "testing_taxonomy_review", "strict": True, "schema": schema},
    }


def call_model(endpoint: str, token: str, model: str, sys_p: str, usr_p: str) -> dict:
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": sys_p},
            {"role": "user", "content": usr_p},
        ],
        "response_format": response_format(),
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{endpoint.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"error: GitHub Models call failed ({e.code}): {e.read().decode('utf-8', 'replace')}")
    content = payload["choices"][0]["message"]["content"]
    return json.loads(content)


def validate(result: dict) -> None:
    """Fail loud if the model's output is off-contract."""
    valid_codes = {r["code"] for r in RULES["rules"]}
    if "models" not in result or not isinstance(result["models"], list):
        sys.exit("error: model output missing 'models' array")
    for m in result["models"]:
        for f in m.get("findings", []):
            if f.get("rule_code") not in valid_codes:
                sys.exit(f"error: model emitted unknown rule_code {f.get('rule_code')!r}")


def render_markdown(result: dict) -> str:
    by_code = {r["code"]: r for r in RULES["rules"]}
    lines = [
        COMMENT_MARKER,
        "## 🧪 Testing-taxonomy review",
        "",
        "Findings from the [`testing-taxonomy-review`](.agents/skills/testing-taxonomy-review/SKILL.md) "
        "skill over the dbt models changed in this PR. `applicable_missing` = a coverage gap to address.",
        "",
    ]
    total_blockers = 0
    for m in result["models"]:
        verdict = VERDICT_BADGE.get(m.get("verdict", ""), m.get("verdict", "?"))
        lines += [f"### `{m['model']}` — {verdict}", "",
                  "| Rule | Status | Severity | Column | Why / Recommendation |",
                  "|------|--------|----------|--------|----------------------|"]
        findings = sorted(
            m.get("findings", []),
            key=lambda f: (f.get("status") != "applicable_missing", SEVERITY_RANK.get(f.get("severity", "info"), 9)),
        )
        for f in findings:
            if f.get("severity") == "blocker" and f.get("status") == "applicable_missing":
                total_blockers += 1
            code = f.get("rule_code", "")
            title = by_code.get(code, {}).get("title", "")
            status = f.get("status", "")
            sev = SEVERITY_BADGE.get(f.get("severity", ""), f.get("severity", ""))
            col = f.get("column", "") or "—"
            why = f"{f.get('rationale', '')} {('— ' + f['recommendation']) if f.get('recommendation') and f['recommendation'] not in ('covered', 'n/a') else ''}".strip()
            lines.append(f"| `{code}` {title} | {status} | {sev} | `{col}` | {why} |")
        lines.append("")
    summary = f"**{len(result['models'])} model(s) reviewed"
    if total_blockers:
        summary += f" · 🔴 {total_blockers} blocker gap(s)**"
    else:
        summary += " · no blocker gaps**"
    lines.insert(2, summary)
    lines.insert(3, "")
    lines += ["<sub>Rule codes: see "
              "[`rules.json`](.agents/skills/testing-taxonomy-review/rules.json) · "
              "vignettes in `docs/guides/testing_taxonomy/`.</sub>"]
    return "\n".join(lines)


def api(method: str, url: str, token: str, data: dict | None = None) -> dict | list:
    req = urllib.request.Request(
        url, method=method,
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


def upsert_comment(repo: str, pr: str, token: str, body: str) -> None:
    base = f"https://api.github.com/repos/{repo}"
    existing = api("GET", f"{base}/issues/{pr}/comments?per_page=100", token)
    mine = next((c for c in existing if COMMENT_MARKER in c.get("body", "")), None)
    if mine:
        api("PATCH", f"{base}/issues/comments/{mine['id']}", token, {"body": body})
        print(f"updated comment {mine['id']}")
    else:
        api("POST", f"{base}/issues/{pr}/comments", token, {"body": body})
        print("created new comment")


def main() -> None:
    token = env("GITHUB_TOKEN")
    repo = env("GITHUB_REPOSITORY")
    pr = env("PR_NUMBER")
    base, head = env("BASE_SHA"), env("HEAD_SHA")
    model = env("MODEL", "openai/gpt-4o")
    endpoint = env("MODELS_ENDPOINT", "https://models.github.ai/inference")
    glob_prefix = env("MODELS_GLOB", "dbt-jaffleshop/models")

    models = changed_models(base, head, glob_prefix)
    if not models:
        print("no changed dbt models — nothing to review")
        return
    print(f"reviewing {len(models)} changed model(s): {', '.join(m.stem for m in models)}")

    result = call_model(endpoint, token, model, system_prompt(), user_prompt(models))
    validate(result)
    body = render_markdown(result)
    upsert_comment(repo, pr, token, body)


if __name__ == "__main__":
    main()
