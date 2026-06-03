Curated snapshot of [`canonical.md`](./canonical.md) — **priced rows only**: the models that
produced a *final estimated price* (a real `Bench cost`). Derived 2026-06-04 from the standardised
one-request `locations` review. Sorted value-first (Findings desc, then Bench cost asc). The full
39-model table (incl. unpriced / un-benchmarked rows) stays in `canonical.md`, which is regenerated
by [`join.py`](./join.py); refresh that, then re-derive this view.

> **Excluded:** `microsoft/mai-ds-r1` — priced ($1.35 / $5.40) but returns `unknown_model` at
> inference, so its `Bench cost` is a meaningless `$0.0000` (0 tokens), not a real estimate.
> **Staleness caveat:** these numbers were measured against the **29-rule** system prompt; the
> catalogue is now **33 rules**, so a re-run of `bench.py` → `join.py` will nudge In-tok / cost /
> findings slightly. Read `Bench cost` alongside `Findings` — a low cost from a low-findings model
> means it under-reviewed, not that it's good value.

| Model | Provider | Tier | Ctx in | Input modes | $/1M in | $/1M out | Bench resp_format | Bench out tok | Bench findings | Bench req (s) | Bench tok/s | Bench cost | Bench status |
|---|---|:--:|--:|---|--:|--:|:--:|--:|--:|--:|--:|--:|---|
| `meta/llama-4-maverick-17b-128e-instruct-fp8` | Meta | high | 1,000,000 | text+image | $0.25 | $1.00 | json_schema | 1,987 | 29 | 19.8 | 100.4 | $0.0026 | ✓ |
| `openai/gpt-4o` | OpenAI | high | 131,072 | text+image+audio | $2.50 | $10.00 | json_schema | 1,455 | 29 | 9.8 | 148.5 | $0.0222 | ✓ |
| `openai/gpt-4.1` | OpenAI | high | 1,048,576 | text+image | $2.00 | $8.00 | json_schema | 2,168 | 29 | 20.4 | 106.3 | $0.0234 | ✓ |
| `openai/gpt-4.1-mini` | OpenAI | low | 1,048,576 | text+image | $0.40 | $1.60 | json_schema | 1,611 | 26 | 29.0 | 55.6 | $0.0038 | ✓ |
| `openai/gpt-4o-mini` | OpenAI | low | 131,072 | text+image+audio | $0.15 | $0.60 | json_schema | 486 | 8 | 9.1 | 53.4 | $0.0007 | ✓ |
| `microsoft/phi-4-multimodal-instruct` | Microsoft | low | 128,000 | audio+image+text | $0.08 | $0.32 | json_schema | 363 | 4 | 35.9 | 10.1 | $0.0003 | ✓ |
| `microsoft/phi-4-mini-instruct` | Microsoft | low | 128,000 | text | $0.08 | $0.30 | json_object | 629 | 0 | 50.0 | 12.6 | $0.0002 | ✓ |
| `microsoft/phi-4` | Microsoft | low | 16,384 | text | $0.13 | $0.50 | json_object | 663 | 0 | 18.1 | 36.6 | $0.0006 | ✓ |
| `meta/llama-3.3-70b-instruct` | Meta | high | 128,000 | text | $0.71 | $0.71 | json_schema | 871 | 0 | 4.9 | 177.8 | $0.0024 | ✓ |
| `deepseek/deepseek-v3-0324` | DeepSeek | high | 128,000 | text | $1.14 | $4.56 | json_schema | 1,025 | 0 | 9.8 | 104.6 | $0.0075 | ✓ |
| `deepseek/deepseek-r1` | DeepSeek | custom | 128,000 | text | $1.35 | $5.40 | json_schema | 1,262 | — | 12.7 | 99.4 | $0.0102 | ✓ |
| `deepseek/deepseek-r1-0528` | DeepSeek | custom | 128,000 | text | $1.35 | $5.40 | json_schema | 7,550 | — | 77.8 | 97.0 | $0.0447 | ✓ |

**12 priced rows** (the `priced` set minus `mai-ds-r1`). Headline: **`meta/llama-4-maverick`** is the
value pick — a full 29-finding review at **$0.0026**, same completeness as `gpt-4o` ($0.0222) for ~9× less.
The four `0`-findings rows (`phi-4`, `phi-4-mini-instruct`, `llama-3.3-70b`, `deepseek-v3-0324`) are
cheap because they didn't actually review — do not use them for this task.
