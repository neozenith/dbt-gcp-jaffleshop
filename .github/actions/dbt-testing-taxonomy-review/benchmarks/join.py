#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Build THE canonical model table(s) by LEFT-JOINing three sources on model id:

  base  = the live GitHub Models catalogue (every model: provider, tier, context, modalities, caps)
  + pricing      = published billing multipliers → $/1M (left join; blank where unpriced)
  + benchmark    = the latest bench.py results (resp_format, tokens, req-time, tok/s, cost, retries)
                   for the models actually trialled (left join; blank where not benchmarked)

Catalogue is fetched live (authoritative). Multipliers are embedded (stable; from the github/docs
billing source — Grok excluded as it returns unknown_model). Benchmark columns are read from the
local `results-priced.md` / `results-newest.md` that bench.py writes.

Two outputs:
  * `canonical.md`        — every catalogue model, all columns (the full reference).
  * `canonical-priced.md` — curated view: only rows with a real final estimated price, value-sorted.

Both carry the free-tier RATE LIMIT (rpm/rpd, from tier), the pure BENCHMARK time (`Req (s)`), the
WALL-CLOCK time (`Wall (s)` = req + rate-limit back-off), and the BACK-OFF share (`Back-off %` =
back-off ÷ wall) — so the rate-limit tax is visible next to raw latency.

Run:  GITHUB_TOKEN=$(gh auth token) uv run --no-project join.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKEN = os.environ.get("GITHUB_TOKEN", "")
# Excluded from the canonical table: Grok (unknown_model at inference) + embedding models
# (not chat-completions — irrelevant to a code-review benchmark).
EXCLUDE = {
    "xai/grok-3", "xai/grok-3-mini",
    "openai/text-embedding-3-large", "openai/text-embedding-3-small",
}

# Published billing multipliers → $/1M = multiplier × $10 (github/docs costs-for-github-models).
PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-4o": (2.50, 10.00), "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4.1": (2.00, 8.00), "openai/gpt-4.1-mini": (0.40, 1.60),
    "microsoft/phi-4": (0.13, 0.50), "microsoft/phi-4-mini-instruct": (0.08, 0.30),
    "microsoft/phi-4-multimodal-instruct": (0.08, 0.32), "microsoft/mai-ds-r1": (1.35, 5.40),
    "deepseek/deepseek-r1": (1.35, 5.40), "deepseek/deepseek-r1-0528": (1.35, 5.40),
    "deepseek/deepseek-v3-0324": (1.14, 4.56),
    "meta/llama-3.3-70b-instruct": (0.71, 0.71),
    "meta/llama-4-maverick-17b-128e-instruct-fp8": (0.25, 1.00),
}

# Free-tier (Copilot Free) rate limits by tier, rpm / rpd — from the github/docs
# prototyping-with-ai-models source. `custom`-tier is per-model and much tighter, with no single
# published number (e.g. o1-preview = 1 rpm), so it is shown as "custom".
RATE_LIMITS: dict[str, str] = {"low": "15 / 150", "high": "10 / 50", "embedding": "15 / 150"}


def free_rate(tier: str) -> str:
    """Free-tier rpm/rpd for a rate-limit tier; 'custom' where it's per-model and unpublished."""
    return RATE_LIMITS.get((tier or "").lower(), "custom")


def timing(req_s: str, rl: str) -> tuple[str, str]:
    """From the bench `Req (s)` + `429 retries (wait s)` cells, derive (wall_s, backoff_pct).

    wall = pure request latency + rate-limit back-off wait; back-off % = wait ÷ wall. A failed run
    (req_s = 0 but non-zero wait) reads as 100% — the rate limit, not the model, was the bottleneck.
    """
    try:
        req = float(req_s)
    except (TypeError, ValueError):
        return "—", "—"
    m = re.search(r"\(([\d.]+)\)", rl or "")
    wait = float(m.group(1)) if m else 0.0
    wall = req + wait
    pct = (wait / wall * 100) if wall > 0 else 0.0
    return f"{wall:.1f}", f"{pct:.0f}%"


def fetch_catalogue() -> list[dict]:
    req = urllib.request.Request(
        "https://models.github.ai/catalog/models",
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 5:
                time.sleep(20 * (attempt + 1))
                continue
            raise
    return []


def parse_results(path: Path) -> dict[str, dict]:
    """Parse a bench results-*.md table → {model_id: {resp_format,in,out,req_s,tok_s,rl,cost,notes}}."""
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*`([^`]+)`\s*\|(.*)\|", line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        # cols after model: tier, ctx_in, resp_format, in, out, findings, req_s, tok_s, rl, cost, notes
        if len(cells) < 11:
            continue
        out[m.group(1)] = {"resp_format": cells[2], "in": cells[3], "out": cells[4],
                           "findings": cells[5], "req_s": cells[6], "tok_s": cells[7],
                           "rl": cells[8], "cost": cells[9], "notes": cells[10]}
    return out


def build_rows(catalogue: list[dict], bench: dict[str, dict]) -> list[dict]:
    """LEFT-JOIN catalogue × pricing × bench into one structured row per model."""
    rows = []
    for m in sorted(catalogue, key=lambda m: (m["publisher"], m["id"])):
        mid = m["id"]
        price = PRICING.get(mid)
        lim = m.get("limits") or {}
        tier = m.get("rate_limit_tier", "?")
        b = bench.get(mid, {})
        req_s = b.get("req_s", "—")
        wall, backoff = timing(req_s, b.get("rl", "—"))
        rows.append({
            "model": mid, "provider": m["publisher"], "tier": tier, "rate": free_rate(tier),
            "ctx": f"{lim.get('max_input_tokens'):,}" if isinstance(lim.get("max_input_tokens"), int) else "?",
            "modes": "+".join(m.get("supported_input_modalities") or []) or "—",
            "in_p": f"${price[0]:.2f}" if price else "—",
            "out_p": f"${price[1]:.2f}" if price else "—",
            "rf": b.get("resp_format", "—"), "out": b.get("out", "—"), "findings": b.get("findings", "—"),
            "req_s": req_s, "wall": wall, "backoff": backoff,
            "tok_s": b.get("tok_s", "—"), "cost": b.get("cost", "—"), "status": b.get("notes", "—"),
        })
    return rows


def _findings_num(s: str) -> int:
    try:
        return int(s)
    except (TypeError, ValueError):
        return -1  # unparseable findings ("—") sort after genuine 0-findings


def _cost_num(s: str) -> float:
    try:
        return float((s or "").lstrip("$"))
    except (TypeError, ValueError):
        return 1e9


# Column specs: (header, row-key). Outcome-first ordering — Bench cost / out tok / findings lead,
# pricing + resp_format trail. The curated priced view is exactly the requested 13 columns; the full
# table keeps the extra reference columns (Ctx in, Input modes, tok/s, status).
PRICED_COLS = [
    ("Model", "model"), ("Provider", "provider"), ("Tier", "tier"), ("Free rpm/rpd", "rate"),
    ("Bench cost", "cost"), ("Bench out tok", "out"), ("Bench findings", "findings"),
    ("Bench req (s)", "req_s"), ("Wall (s)", "wall"), ("Back-off %", "backoff"),
    ("$/1M in", "in_p"), ("$/1M out", "out_p"), ("Bench resp_format", "rf"),
]
FULL_COLS = [
    ("Model", "model"), ("Provider", "provider"), ("Tier", "tier"), ("Free rpm/rpd", "rate"),
    ("Ctx in", "ctx"), ("Input modes", "modes"),
    ("Bench cost", "cost"), ("Bench out tok", "out"), ("Bench findings", "findings"),
    ("Bench req (s)", "req_s"), ("Wall (s)", "wall"), ("Back-off %", "backoff"),
    ("Bench tok/s", "tok_s"), ("$/1M in", "in_p"), ("$/1M out", "out_p"),
    ("Bench resp_format", "rf"), ("Bench status", "status"),
]
# Right-align numeric-ish columns; center the short categorical ones.
_RIGHT = {"Ctx in", "$/1M in", "$/1M out", "Bench out tok", "Bench findings", "Bench req (s)",
          "Wall (s)", "Back-off %", "Bench tok/s", "Bench cost"}
_CENTER = {"Tier", "Free rpm/rpd", "Bench resp_format"}


def render(rows: list[dict], cols: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(h for h, _ in cols) + " |"
    sep = "|" + "|".join(":--:" if h in _CENTER else "--:" if h in _RIGHT else "---"
                         for h, _ in cols) + "|"
    body = ["| " + " | ".join(f"`{r[k]}`" if k == "model" else str(r[k]) for _, k in cols) + " |"
            for r in rows]
    return "\n".join([head, sep, *body])


def main() -> None:
    if not TOKEN:
        sys.exit("error: set GITHUB_TOKEN (e.g. GITHUB_TOKEN=$(gh auth token))")
    catalogue = [m for m in fetch_catalogue() if m["id"] not in EXCLUDE]
    bench = {**parse_results(HERE / "results-priced.md"), **parse_results(HERE / "results-newest.md")}
    rows = build_rows(catalogue, bench)

    benchmarked = sum(1 for r in rows if r["model"] in bench)
    priced = sum(1 for r in rows if r["model"] in PRICING)

    # ---- canonical.md (full) ----
    caption = (f"Canonical table — {len(rows)} catalogue models LEFT-JOINed with pricing "
               f"({priced} priced) and benchmark results ({benchmarked} trialled). "
               f"Blank/— = not priced / not benchmarked. Bench columns are ONE fixed-capability "
               f"review of `locations` against the **29-rule** catalogue (held constant — only model "
               f"performance/cost varies). **Free rpm/rpd** = free-tier rate limit by tier; "
               f"**Wall (s)** = `Bench req (s)` + rate-limit back-off; **Back-off %** = "
               f"back-off ÷ wall. Generated by `join.py`.")
    full = "\n".join([caption, "", render(rows, FULL_COLS)])
    (HERE / "canonical.md").write_text(full + "\n", encoding="utf-8")

    # ---- canonical-priced.md (curated: real final estimated price only, value-sorted) ----
    priced_rows = [r for r in rows
                   if r["model"] in PRICING and r["cost"].startswith("$") and r["cost"] != "$0.0000"]
    priced_rows.sort(key=lambda r: (-_findings_num(r["findings"]), _cost_num(r["cost"])))
    excluded = sorted(mid for mid in PRICING
                      if mid not in {r["model"] for r in priced_rows} and mid in bench)
    note = (
        f"Curated view of [`canonical.md`](./canonical.md) — **priced rows only** ({len(priced_rows)} "
        f"of {priced} priced models that returned a real *final estimated price*), value-sorted "
        f"(Findings desc, then Bench cost asc). Bench columns are ONE fixed-capability `locations` "
        f"review against the **29-rule** catalogue, held constant — only model performance/cost "
        f"varies. **Free rpm/rpd** = free-tier rate limit by tier; **Wall (s)** = `Bench req (s)` + "
        f"rate-limit back-off; **Back-off %** = back-off ÷ wall. Generated by `join.py` (do not "
        f"hand-edit).\n")
    if excluded:
        note += ("\n> **Excluded** (priced but no real estimate): "
                 + ", ".join(f"`{e}`" for e in excluded)
                 + " — returned `unknown_model` / errored, so cost is a 0-token `$0.0000`.\n")
    note += ("> **Read `Bench cost` with `Findings`**: a low cost from a low-findings model means it "
             "under-reviewed, not that it's good value. **Back-off %** isolates the free-tier "
             "rate-limit tax from the model's own latency.\n")
    curated = note + "\n" + render(priced_rows, PRICED_COLS)
    (HERE / "canonical-priced.md").write_text(curated + "\n", encoding="utf-8")

    print(f"wrote canonical.md ({len(rows)} rows; {priced} priced; {benchmarked} benchmarked) "
          f"and canonical-priced.md ({len(priced_rows)} rows)")


if __name__ == "__main__":
    main()
