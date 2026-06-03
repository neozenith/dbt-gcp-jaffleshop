#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Empirical model trials for the testing-taxonomy review workload.

Runs the SAME review prompt (system catalogue + a fixed set of dbt models, batched the same
way as production) against a curated, provider-diverse set of GitHub-hosted models, and records
the REAL: input/output token counts, API call counts, wall-clock seconds, and estimated cost.

Cost uses GitHub Models' own multipliers (effective $/1M = multiplier × $10; see MODELS.md).
GitHub Models' free tier may bill $0 — the cost column is the at-list-price equivalent so models
are comparable.

Reuses the production engine's prompt + batching (imports review.py). For each model it tries the
response_format ladder json_schema → json_object → none, recording which mode the model accepted
(so "structured-output support" is part of the result). Resilient: a model that errors is recorded
and the run continues.

Run locally:  GITHUB_TOKEN=$(gh auth token) uv run --no-project bench.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import review  # noqa: E402  (reuse system_prompt/user_prompt/batch_models/est_tokens/REQUEST_TOKEN_CAP)

ENDPOINT = os.environ.get("MODELS_ENDPOINT", "https://models.github.ai/inference")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Curated set: >=8 models across 5 providers, every one with a published GitHub Models
# multiplier. (input $/1M, output $/1M) = multiplier * $10.
PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4.1-mini": (0.40, 1.60),
    "microsoft/phi-4": (0.125, 0.50),
    "microsoft/phi-4-mini-instruct": (0.075, 0.30),
    "deepseek/deepseek-v3-0324": (1.14, 4.56),
    "xai/grok-3-mini": (0.25, 1.27),
    "xai/grok-3": (3.00, 15.00),
    "meta/llama-3.3-70b-instruct": (0.71, 0.71),
    "meta/llama-4-maverick-17b-128e-instruct-fp8": (0.25, 1.00),
}
MODELS = list(PRICING)


def bench_input() -> list[Path]:
    """Fixed, representative input: the mart models (the substantive ones; multi-batch)."""
    return sorted((Path("dbt-jaffleshop/models/marts")).glob("*.sql"))


def _post(model: str, sys_p: str, usr_p: str, rformat: dict | None) -> dict:
    payload: dict = {"model": model, "temperature": 0,
                     "messages": [{"role": "system", "content": sys_p},
                                  {"role": "user", "content": usr_p}]}
    if rformat is not None:
        payload["response_format"] = rformat
    req = urllib.request.Request(
        f"{ENDPOINT.rstrip('/')}/chat/completions", data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
                 "Accept": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=240) as resp:
        return json.loads(resp.read().decode("utf-8")).get("usage") or {}


def call_with_fallback(model: str, sys_p: str, usr_p: str) -> tuple[dict, str | None, str | None]:
    """Try json_schema → json_object → plain. Return (usage, mode_used, error)."""
    modes = [("json_schema", review.response_format()), ("json_object", {"type": "json_object"}), ("plain", None)]
    last_err = None
    for name, rf in modes:
        for attempt in range(4):
            try:
                return _post(model, sys_p, usr_p, rf), name, None
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:140]
                if e.code == 429 and attempt < 3:
                    time.sleep(min(60, 10 * (2 ** attempt)))
                    continue
                last_err = f"{e.code} ({name}): {detail}"
                break  # non-429: downgrade response_format and retry
            except Exception as e:  # noqa: BLE001
                last_err = f"{name}: {e}"
                break
    return {}, None, last_err


def bench_model(model: str, models: list[Path]) -> dict:
    sys_p = review.system_prompt()
    overhead = review.est_tokens(sys_p) + review.est_tokens(json.dumps(review.response_format()))
    budget = max(1500, review.REQUEST_TOKEN_CAP - overhead)
    batches = review.batch_models(models, budget)
    pin = pout = calls = 0
    mode = None
    err = None
    t0 = time.perf_counter()
    for b in batches:
        usage, used_mode, e = call_with_fallback(model, sys_p, review.user_prompt(b))
        if e:
            err = e
            break
        mode = used_mode
        pin += int(usage.get("prompt_tokens", 0) or 0)
        pout += int(usage.get("completion_tokens", 0) or 0)
        calls += 1
        time.sleep(6)  # spacing for free-tier per-minute limits
    wall = time.perf_counter() - t0
    in_p, out_p = PRICING[model]
    cost = pin / 1e6 * in_p + pout / 1e6 * out_p
    return {"model": model, "mode": mode, "calls": calls, "in": pin, "out": pout,
            "total": pin + pout, "wall_s": round(wall, 1), "cost": cost, "error": err}


def main() -> None:
    if not TOKEN:
        sys.exit("error: set GITHUB_TOKEN (e.g. GITHUB_TOKEN=$(gh auth token))")
    models = bench_input()
    print(f"benchmark input: {len(models)} models — {', '.join(m.stem for m in models)}\n")
    rows = []
    for i, model in enumerate(MODELS):
        print(f"[{i + 1}/{len(MODELS)}] {model} …", flush=True)
        r = bench_model(model, models)
        rows.append(r)
        print(f"    -> mode={r['mode']} calls={r['calls']} in={r['in']} out={r['out']} "
              f"wall={r['wall_s']}s cost=${r['cost']:.4f}" + (f" ERROR={r['error']}" if r['error'] else ""))
        if i + 1 < len(MODELS):
            time.sleep(8)
    # Markdown results table, cheapest-first among successful runs.
    rows.sort(key=lambda r: (r["error"] is not None, r["cost"]))
    out = ["| Model | resp_format | API calls | Input tok | Output tok | Total tok | Wall (s) | Est. cost (USD) | Notes |",
           "|---|:---:|:---:|---:|---:|---:|---:|---:|---|"]
    for r in rows:
        notes = "✓" if not r["error"] else f"⚠️ {r['error']}"
        cost = "—" if r["error"] else f"${r['cost']:.4f}"
        out.append(f"| `{r['model']}` | {r['mode'] or '—'} | {r['calls']} | {r['in']:,} | {r['out']:,} | "
                   f"{r['total']:,} | {r['wall_s']} | {cost} | {notes} |")
    table = "\n".join(out)
    print("\n" + table)
    results_path = Path(__file__).resolve().parent / "results.md"
    results_path.write_text(table + "\n", encoding="utf-8")
    print(f"\nwrote {results_path}")


if __name__ == "__main__":
    main()
