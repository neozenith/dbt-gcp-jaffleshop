#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Build THE single canonical model table by LEFT-JOINing three sources on model id:

  base  = the live GitHub Models catalogue (every model: provider, tier, context, modalities, caps)
  + pricing      = published billing multipliers → $/1M (left join; blank where unpriced)
  + benchmark    = the latest bench.py results (resp_format, tokens, req-time, tok/s, cost) for the
                   models actually trialled (left join; blank where not benchmarked)

Catalogue is fetched live (authoritative). Multipliers are embedded (stable; from the github/docs
billing source — Grok excluded as it returns unknown_model). Benchmark columns are read from the
local `results-priced.md` / `results-newest.md` that bench.py writes. Output: `canonical.md`.

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


def main() -> None:
    if not TOKEN:
        sys.exit("error: set GITHUB_TOKEN (e.g. GITHUB_TOKEN=$(gh auth token))")
    catalogue = [m for m in fetch_catalogue() if m["id"] not in EXCLUDE]
    bench = {**parse_results(HERE / "results-priced.md"), **parse_results(HERE / "results-newest.md")}

    rows = []
    for m in sorted(catalogue, key=lambda m: (m["publisher"], m["id"])):
        mid = m["id"]
        price = PRICING.get(mid)
        in_p = f"${price[0]:.2f}" if price else "—"
        out_p = f"${price[1]:.2f}" if price else "—"
        lim = m.get("limits") or {}
        b = bench.get(mid, {})
        rows.append("| " + " | ".join([
            f"`{mid}`", m["publisher"], m.get("rate_limit_tier", "?"),
            f"{lim.get('max_input_tokens', '?'):,}" if isinstance(lim.get("max_input_tokens"), int) else "?",
            "+".join(m.get("supported_input_modalities") or []) or "—",
            in_p, out_p,
            b.get("resp_format", "—"), b.get("out", "—"), b.get("findings", "—"),
            b.get("req_s", "—"), b.get("tok_s", "—"), b.get("cost", "—"), b.get("notes", "—"),
        ]) + " |")

    header = ("| Model | Provider | Tier | Ctx in | Input modes | $/1M in | $/1M out | "
              "Bench resp_format | Bench out tok | Bench findings | Bench req (s) | Bench tok/s | "
              "Bench cost | Bench status |")
    sep = "|---|---|:--:|--:|---|--:|--:|:--:|--:|--:|--:|--:|--:|---|"
    benchmarked = sum(1 for m in catalogue if m["id"] in bench)
    priced = sum(1 for m in catalogue if m["id"] in PRICING)
    caption = (f"Canonical table — {len(catalogue)} catalogue models LEFT-JOINed with pricing "
               f"({priced} priced) and benchmark results ({benchmarked} trialled). "
               f"Blank/— = not priced / not benchmarked. Generated by `join.py`.")
    table = "\n".join([caption, "", header, sep, *rows])
    print(table)
    (HERE / "canonical.md").write_text(table + "\n", encoding="utf-8")
    print(f"\nwrote {HERE / 'canonical.md'}  ({len(catalogue)} rows; {priced} priced; {benchmarked} benchmarked)")


if __name__ == "__main__":
    main()
