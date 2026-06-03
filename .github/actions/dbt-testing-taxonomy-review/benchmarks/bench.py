#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Empirical model trials for the testing-taxonomy review workload — ONE standardised example.

Runs a SINGLE, fixed code-review request (the production system catalogue + the `orders` mart) —
small enough to fit in one request under the tightest tier cap (4000 input tokens) so EVERY model
does it in exactly one request and is directly comparable. For each model it records the REAL:
input/output token counts, **pure request latency** (`req_s`), **true output throughput**
(`tok/s = out ÷ req_s`), estimated cost, and — measured SEPARATELY — any rate-limit retries and the
time spent waiting on them (`rl_wait_s`). Crucially, req_s/tok-s EXCLUDE rate-limit backoff and
inter-model spacing, so throughput is not polluted by 429 waits (the bug this run fixes).

Rate-limit context (free tier / Copilot Free, per GitHub docs): Low = 15 rpm / 150 rpd, High =
10 rpm / 50 rpd, both 8000 in / 4000 out tokens per request; several reasoning models impose a
tighter 4000-input cap. See MODELS.md.

Cost uses GitHub Models' own multipliers ($/1M = multiplier × $10; unpriced models → None).
For each model it tries the response_format ladder json_schema → json_object → plain and drops
`temperature` if rejected (gpt-5/o-series). Resilient: a model that errors is recorded and the
run continues.

Run locally:  BENCH_SET=priced|newest GITHUB_TOKEN=$(gh auth token) uv run --no-project bench.py
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
# (input $/1M, output $/1M) = GitHub Models multiplier × $10. Only models with a published
# multiplier appear here; others → cost shown as "—" (no published rate).
PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4.1-mini": (0.40, 1.60),
    "microsoft/phi-4": (0.125, 0.50),
    "microsoft/phi-4-mini-instruct": (0.075, 0.30),
    "deepseek/deepseek-v3-0324": (1.14, 4.56),
    "deepseek/deepseek-r1-0528": (1.35, 5.40),
    "xai/grok-3-mini": (0.25, 1.27),
    "xai/grok-3": (3.00, 15.00),
    "meta/llama-3.3-70b-instruct": (0.71, 0.71),
    "meta/llama-4-maverick-17b-128e-instruct-fp8": (0.25, 1.00),
}

# Selectable benchmark sets (BENCH_SET=priced|newest, default priced).
SETS: dict[str, list[str]] = {
    "priced": [
        "openai/gpt-4o", "openai/gpt-4o-mini", "openai/gpt-4.1-mini",
        "microsoft/phi-4", "microsoft/phi-4-mini-instruct", "deepseek/deepseek-v3-0324",
        "xai/grok-3-mini", "xai/grok-3", "meta/llama-3.3-70b-instruct",
        "meta/llama-4-maverick-17b-128e-instruct-fp8",
    ],
    # The 8 newest / flagship models (mostly reasoning, "custom" rate tier; several have no
    # published price multiplier yet — cost will read "—").
    "newest": [
        "openai/gpt-5", "openai/gpt-5-mini", "openai/gpt-5-nano",
        "openai/o3", "openai/o4-mini", "xai/grok-3",
        "meta/llama-4-scout-17b-16e-instruct", "deepseek/deepseek-r1-0528",
    ],
}
MODELS = SETS.get(os.environ.get("BENCH_SET", "priced"), SETS["priced"])


def load_catalogue() -> dict[str, dict]:
    """Fetch the live catalogue once → {id: {tier, ctx_in, capabilities}} for annotation."""
    req = urllib.request.Request(
        "https://models.github.ai/catalog/models",
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            return {m["id"]: {"tier": m.get("rate_limit_tier", "?"),
                              "ctx_in": (m.get("limits") or {}).get("max_input_tokens"),
                              "caps": "+".join(m.get("capabilities") or []) or "—"}
                    for m in data}
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                time.sleep(20 * (attempt + 1))
                continue
            break
        except Exception:  # noqa: BLE001
            break
    print("  (catalogue metadata unavailable — proceeding without tier/ctx/caps)")
    return {}


# THE standardised code-review example: review ONE small mart (`locations`) + its YAML in a SINGLE
# request. `locations` is deliberately chosen so the whole request (system catalogue + schema +
# model ≈ 2,950 input tokens) stays well under 4000 — the tightest per-request input cap (reasoning
# models on the free tier). That way EVERY model completes the example in exactly one request, with
# no batching and no inter-batch sleeps, so req-time and tok/s are clean and directly comparable.
# (The big marts — orders/customers/order_items — exceed 4000 input alone, so they can't be a
# common baseline across the 4000-cap models; that limitation is itself a finding in MODELS.md.)
STANDARD_INPUT = [Path("dbt-jaffleshop/models/marts/locations.sql")]


def _post(model: str, sys_p: str, usr_p: str, rformat: dict | None, with_temp: bool) -> tuple[dict, float]:
    """POST one request; return (usage, request_seconds) where request_seconds is the PURE network +
    generation latency of this call (excludes any retry/backoff waits, which happen outside _post)."""
    payload: dict = {"model": model,
                     "messages": [{"role": "system", "content": sys_p},
                                  {"role": "user", "content": usr_p}]}
    if with_temp:
        payload["temperature"] = 0  # deterministic; reasoning models (gpt-5/o*) reject this
    if rformat is not None:
        payload["response_format"] = rformat
    req = urllib.request.Request(
        f"{ENDPOINT.rstrip('/')}/chat/completions", data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
                 "Accept": "application/json"}, method="POST")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as resp:
        usage = json.loads(resp.read().decode("utf-8")).get("usage") or {}
    return usage, time.perf_counter() - t0


def call_with_fallback(model: str, sys_p: str, usr_p: str) -> dict:
    """One standardised request with fallbacks: json_schema → json_object → plain, and drop
    temperature if rejected (gpt-5/o-series). Separates PURE request time from rate-limit wait:
    returns {usage, mode, req_s, retries, rl_wait_s, error}."""
    modes = [("json_schema", review.response_format()), ("json_object", {"type": "json_object"}), ("plain", None)]
    retries = 0
    rl_wait = 0.0
    last_err = None
    for name, rf in modes:
        with_temp = True
        for attempt in range(5):
            try:
                usage, req_s = _post(model, sys_p, usr_p, rf, with_temp)
                return {"usage": usage, "mode": name, "req_s": req_s,
                        "retries": retries, "rl_wait_s": rl_wait, "error": None}
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                if e.code == 429 and attempt < 4:
                    wait = min(60, 10 * (2 ** attempt))
                    retries += 1
                    rl_wait += wait
                    time.sleep(wait)  # rate-limit wait — tracked separately, NOT counted as req time
                    continue
                if e.code == 400 and with_temp and "temperature" in detail.lower():
                    with_temp = False
                    continue
                last_err = f"{e.code} ({name}): {detail[:120]}"
                break
            except Exception as e:  # noqa: BLE001
                last_err = f"{name}: {e}"
                break
    return {"usage": {}, "mode": None, "req_s": 0.0, "retries": retries, "rl_wait_s": rl_wait, "error": last_err}


def bench_model(model: str, meta: dict) -> dict:
    """Run THE standardised example (one request) and measure pure request latency + true tok/s."""
    sys_p = review.system_prompt()
    r = call_with_fallback(model, sys_p, review.user_prompt(STANDARD_INPUT))
    usage = r["usage"]
    pin = int(usage.get("prompt_tokens", 0) or 0)
    pout = int(usage.get("completion_tokens", 0) or 0)
    req_s = round(r["req_s"], 1)
    price = PRICING.get(model)
    cost = (pin / 1e6 * price[0] + pout / 1e6 * price[1]) if price else None
    tok_s = round(pout / req_s, 1) if req_s > 0 and pout else 0.0  # TRUE output throughput
    m = meta.get(model, {})
    return {"model": model, "tier": m.get("tier", "?"), "ctx_in": m.get("ctx_in"),
            "mode": r["mode"], "in": pin, "out": pout, "req_s": req_s, "tok_s": tok_s,
            "retries": r["retries"], "rl_wait_s": round(r["rl_wait_s"], 1), "cost": cost,
            "error": r["error"]}


def main() -> None:
    if not TOKEN:
        sys.exit("error: set GITHUB_TOKEN (e.g. GITHUB_TOKEN=$(gh auth token))")
    set_name = os.environ.get("BENCH_SET", "priced")
    meta = load_catalogue()
    print(f"set={set_name} · standardised example: review `{STANDARD_INPUT[0].stem}` in ONE request\n")
    rows = []
    for i, model in enumerate(MODELS):
        print(f"[{i + 1}/{len(MODELS)}] {model} …", flush=True)
        r = bench_model(model, meta)
        rows.append(r)
        cost_s = "—" if r["cost"] is None else f"${r['cost']:.4f}"
        print(f"    -> tier={r['tier']} mode={r['mode']} in={r['in']} out={r['out']} "
              f"req={r['req_s']}s tok/s={r['tok_s']} retries={r['retries']} (rl_wait={r['rl_wait_s']}s) "
              f"cost={cost_s}" + (f" ERROR={r['error']}" if r['error'] else ""))
        if i + 1 < len(MODELS):
            time.sleep(8)  # spacing between models (NOT counted in any model's req time)
    # Sort: successful first, then fastest generator (tok/s desc), then cheapest.
    rows.sort(key=lambda r: (r["error"] is not None, -r["tok_s"], r["cost"] is None, r["cost"] or 0.0))
    hdr = ("| Model | tier | ctx in | resp_format | In tok | Out tok | Req (s) | Tok/s | "
           "429 retries (wait s) | Est. cost | Notes |")
    out = [hdr, "|---|:---:|--:|:---:|--:|--:|--:|--:|:--:|--:|---|"]
    for r in rows:
        cost = "—" if r["cost"] is None else f"${r['cost']:.4f}"
        ctx = f"{r['ctx_in']:,}" if r["ctx_in"] else "?"
        rl = f"{r['retries']} ({r['rl_wait_s']})" if r["retries"] else "0"
        note = "✓" if not r["error"] else f"⚠️ {r['error']}"
        out.append(f"| `{r['model']}` | {r['tier']} | {ctx} | {r['mode'] or '—'} | "
                   f"{r['in']:,} | {r['out']:,} | {r['req_s']} | {r['tok_s']} | {rl} | {cost} | {note} |")
    table = "\n".join(out)
    print("\n" + table)
    results_path = Path(__file__).resolve().parent / f"results-{set_name}.md"
    results_path.write_text(table + "\n", encoding="utf-8")
    print(f"\nwrote {results_path}")


if __name__ == "__main__":
    main()
