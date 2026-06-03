# GitHub-hosted models — pricing & empirical trials

Reference for choosing the `model` input of the
[`dbt-testing-taxonomy-review`](../README.md) action:

1. **Pricing & rate limits** — the GitHub Models catalogue, GitHub's cost multipliers, and the
   free-tier rate limits + per-request token caps (all from authoritative GitHub sources).
2. **Empirical trials** — real token / pure-request-latency / true-throughput / cost measurements
   running ONE standardised review request against a provider-diverse set of models (via
   [`bench.py`](./bench.py)).

## How GitHub Models bills

GitHub Models charges **$0.00001 per token unit**. Token units = actual tokens × the model's
**multiplier** (separate input and output multipliers). So the at-list-price rate is:

```
$ / 1M tokens  =  multiplier × 1,000,000 × $0.00001  =  multiplier × $10
```

> The **free tier may bill $0** (rate-limited). The prices below are the at-list-price
> equivalent, so models are comparable regardless of which tier actually runs them.

### Sources — how to get the raw markdown

The catalogue API has **no pricing or rate-limit data**. Those live only in GitHub's docs, but
every docs page has a parseable source: **`docs.github.com/en/<path>` → `raw.githubusercontent.com/github/docs/main/content/<path>.md`**. The three relevant sources:

| Docs page | Raw markdown (`…/github/docs/main/content/…`) | Gives |
|-----------|-----------------------------------------------|-------|
| `billing/reference/costs-for-github-models` | `…/billing/reference/costs-for-github-models.md` | input/cached/output **multipliers** + prices |
| `github-models/use-github-models/prototyping-with-ai-models` (#rate-limits) | `…/github-models/use-github-models/prototyping-with-ai-models.md` | **rate limits** (rpm/rpd/tokens-per-request/concurrent) per plan |
| `copilot/reference/copilot-billing/models-and-pricing` | `…/copilot/reference/copilot-billing/models-and-pricing.md` | Copilot-IDE **premium-request** multipliers — a *separate* billing axis, **not** the Models-API direct cost used here |

The [`github models catalog`](../../../workflows/github-models-catalog.yml) workflow fetches the
catalogue (via `GITHUB_TOKEN`) **and** the multipliers (via the docs source) and prints both to the
run log / job summary / artifact. Working backwards from a multiplier: **`$/1M = multiplier × $10`**
(the doc also lists precomputed prices, which match). Refresh: `gh workflow run "github models catalog" --ref main`.

### Rate limits & per-request token caps (free tier)

From the prototyping-with-ai-models source (column = **Copilot Free**, the free tier). This explains
both the 429s and the 413s the trials hit:

| Model tier | Requests/min | Requests/**day** | Tokens per request | Concurrent |
|------------|-------------:|-----------------:|--------------------|-----------:|
| **Low** | 15 | **150** | 8000 in / 4000 out | 5 |
| **High** | 10 | **50** | 8000 in / 4000 out | 2 |
| **Embedding** | 15 | 150 | 64000 | 5 |
| **Custom** (per-model; reasoning, gpt-5/o*, deepseek, grok) | model-specific & much tighter (e.g. `o1-preview` = 1 rpm) | — | observed **4000 in** | — |

Implications for this action:
- **High-tier models get only 50 requests/day on the free tier** — `gpt-4o`, `gpt-4.1`,
  `deepseek-v3`, the Llamas are *high* tier, so heavy use exhausts the daily quota fast (the source
  of the 429s here). *Low*-tier (`gpt-4o-mini`, `gpt-4.1-mini`, Phi) gets 150/day.
- **Per-request cap is 8000 in / 4000 out** for Low/High; **reasoning/custom models cap at 4000 in**
  (observed via `413 tokens_limit_reached`). The action's batch budget (`REQUEST_TOKEN_CAP`) must
  stay under the cap of the chosen model — 7000 works for 8000-cap models, but a 4000-cap model
  needs ≤ ~3000.
- Paid tiers (Pro/Business/Enterprise) raise requests/day (and Enterprise raises tokens/request to
  16000 in / 8000 out on High). Re-run the catalogue workflow to refresh if the plan changes.

### Billing multipliers (GHA-extracted, all priced models)

The complete table as published by GitHub — extracted from run `26885409627`. `$/1M = mult × $10`.
Cached-input applies only where the model supports prompt caching.

| Model id | Provider | In mult | Cached-in mult | Out mult | $/1M in | $/1M cached-in | $/1M out |
|----------|----------|--------:|---------------:|---------:|--------:|---------------:|--------:|
| `openai/gpt-4o` | OpenAI | 0.25 | 0.125 | 1.0 | $2.50 | $1.25 | $10.00 |
| `openai/gpt-4o-mini` | OpenAI | 0.015 | 0.0075 | 0.06 | $0.15 | $0.08 | $0.60 |
| `openai/gpt-4.1` | OpenAI | 0.2 | 0.05 | 0.8 | $2.00 | $0.50 | $8.00 |
| `openai/gpt-4.1-mini` | OpenAI | 0.04 | 0.01 | 0.16 | $0.40 | $0.10 | $1.60 |
| `microsoft/phi-4` | Microsoft | 0.0125 | — | 0.05 | $0.13 | — | $0.50 |
| `microsoft/phi-4-mini-instruct` | Microsoft | 0.0075 | — | 0.03 | $0.08 | — | $0.30 |
| `microsoft/phi-4-multimodal-instruct` | Microsoft | 0.008 | — | 0.032 | $0.08 | — | $0.32 |
| `deepseek/deepseek-r1` | DeepSeek | 0.135 | — | 0.54 | $1.35 | — | $5.40 |
| `deepseek/deepseek-r1-0528` | DeepSeek | 0.135 | — | 0.54 | $1.35 | — | $5.40 |
| `deepseek/deepseek-v3-0324` | DeepSeek | 0.114 | — | 0.456 | $1.14 | — | $4.56 |
| `microsoft/mai-ds-r1` | Microsoft | 0.135 | — | 0.54 | $1.35 | — | $5.40 |
| `xai/grok-3-mini` | xAI | 0.025 | — | 0.127 | $0.25 | — | $1.27 |
| `xai/grok-3` | xAI | 0.3 | — | 1.5 | $3.00 | — | $15.00 |
| `meta/llama-4-maverick-17b-128e-instruct-fp8` | Meta | 0.025 | — | 0.1 | $0.25 | — | $1.00 |
| `meta/llama-3.3-70b-instruct` | Meta | 0.071 | — | 0.071 | $0.71 | — | $0.71 |

> Only these 15 models have published multipliers. The other ~26 catalogue entries (Cohere,
> Mistral AI, AI21 Labs, the OpenAI `gpt-5`/`o`-series, `llama-4-scout`, Grok via some ids, …)
> are inferenceable but **unpriced** in the doc — so their at-list-price cost can't be stated,
> and they show `—` in the trial results below.

### Full live catalogue (authoritative, via GHA)

The complete, up-to-date listing is fetched by the
[`github models catalog`](../../../workflows/github-models-catalog.yml) workflow using the
runner's `GITHUB_TOKEN` (`models: read`) and read from the run log / job summary — reproducible,
not hand-maintained. Refresh: `gh workflow run "github models catalog" --ref main`.

> **The catalogue API exposes no pricing** — only id / publisher / rate-limit tier / context
> limits / modalities / capabilities (confirmed via the GHA: the model objects carry no price
> field). So **listings** come from the catalogue (live) and **prices** from the billing
> multipliers above (multiplier × $10) — there is no single endpoint with both.

<details>
<summary>43 models — GHA-extracted 2026-06-03 (run 26883567820)</summary>

| id | publisher | tier | ctx in | ctx out | input | capabilities |
|----|-----------|------|-------:|--------:|-------|--------------|
| `ai21-labs/ai21-jamba-1.5-large` | AI21 Labs | high | 262144 | 4096 | text | streaming, tool-calling |
| `cohere/cohere-command-a` | Cohere | low | 131072 | 4096 | text | — |
| `cohere/cohere-command-r-08-2024` | Cohere | low | 131072 | 4096 | text | streaming |
| `cohere/cohere-command-r-plus-08-2024` | Cohere | high | 131072 | 4096 | text | streaming, tool-calling |
| `deepseek/deepseek-r1` | DeepSeek | custom | 128000 | 4096 | text | reasoning, streaming, tool-calling |
| `deepseek/deepseek-r1-0528` | DeepSeek | custom | 128000 | 4096 | text | agentsV2, reasoning, streaming, tool-calling |
| `deepseek/deepseek-v3-0324` | DeepSeek | high | 128000 | 4096 | text | agentsV2, streaming, tool-calling |
| `meta/llama-3.2-11b-vision-instruct` | Meta | low | 128000 | 4096 | text+image+audio | streaming |
| `meta/llama-3.2-90b-vision-instruct` | Meta | high | 128000 | 4096 | text+image+audio | streaming |
| `meta/llama-3.3-70b-instruct` | Meta | high | 128000 | 4096 | text | agentsV2, streaming |
| `meta/llama-4-maverick-17b-128e-instruct-fp8` | Meta | high | 1000000 | 4096 | text+image | agents, agentsV2, assistants, streaming, tool-calling |
| `meta/llama-4-scout-17b-16e-instruct` | Meta | high | 10000000 | 4096 | text+image | agents, assistants, streaming, tool-calling |
| `meta/meta-llama-3.1-405b-instruct` | Meta | high | 131072 | 4096 | text | agents |
| `meta/meta-llama-3.1-8b-instruct` | Meta | low | 131072 | 4096 | text | streaming |
| `microsoft/mai-ds-r1` | Microsoft | custom | 128000 | 4096 | text | agentsV2, reasoning, streaming |
| `microsoft/phi-4` | Microsoft | low | 16384 | 16384 | text | — |
| `microsoft/phi-4-mini-instruct` | Microsoft | low | 128000 | 4096 | text | — |
| `microsoft/phi-4-mini-reasoning` | Microsoft | low | 128000 | 4096 | text | reasoning |
| `microsoft/phi-4-multimodal-instruct` | Microsoft | low | 128000 | 4096 | audio+image+text | streaming |
| `microsoft/phi-4-reasoning` | Microsoft | low | 32768 | 4096 | text | reasoning, streaming |
| `mistral-ai/codestral-2501` | Mistral AI | low | 256000 | 4096 | text | streaming |
| `mistral-ai/ministral-3b` | Mistral AI | low | 131072 | 4096 | text | streaming, tool-calling |
| `mistral-ai/mistral-medium-2505` | Mistral AI | low | 128000 | 4096 | text+image | streaming, tool-calling |
| `mistral-ai/mistral-small-2503` | Mistral AI | low | 128000 | 4096 | text+image | agents, assistants, streaming, tool-calling |
| `openai/gpt-4.1` | OpenAI | high | 1048576 | 32768 | text+image | agents, streaming, tool-calling, agentsV2 |
| `openai/gpt-4.1-mini` | OpenAI | low | 1048576 | 32768 | text+image | agents, streaming, tool-calling, agentsV2 |
| `openai/gpt-4.1-nano` | OpenAI | low | 1048576 | 32768 | text+image | agents, streaming, tool-calling, agentsV2 |
| `openai/gpt-4o` | OpenAI | high | 131072 | 16384 | text+image+audio | agents, assistants, streaming, tool-calling, agentsV2 |
| `openai/gpt-4o-mini` | OpenAI | low | 131072 | 4096 | text+image+audio | agents, assistants, streaming, tool-calling, agentsV2 |
| `openai/gpt-5` | OpenAI | custom | 200000 | 100000 | text+image | agents, agentsV2, reasoning, tool-calling, streaming |
| `openai/gpt-5-chat` | OpenAI | custom | 200000 | 100000 | text+image | agents, agentsV2, reasoning, tool-calling, streaming |
| `openai/gpt-5-mini` | OpenAI | custom | 200000 | 100000 | text+image | agents, agentsV2, reasoning, tool-calling, streaming |
| `openai/gpt-5-nano` | OpenAI | custom | 200000 | 100000 | text+image | agents, agentsV2, reasoning, tool-calling, streaming |
| `openai/o1` | OpenAI | custom | 200000 | 100000 | text+image | agents, reasoning, tool-calling, agentsV2 |
| `openai/o1-mini` | OpenAI | custom | 128000 | 65536 | text | reasoning, streaming, agentsV2 |
| `openai/o1-preview` | OpenAI | custom | 128000 | 32768 | text | agentsV2, reasoning |
| `openai/o3` | OpenAI | custom | 200000 | 100000 | text+image | agents, agentsV2, reasoning, streaming, tool-calling |
| `openai/o3-mini` | OpenAI | custom | 200000 | 100000 | text | agents, reasoning, streaming, tool-calling, agentsV2 |
| `openai/o4-mini` | OpenAI | custom | 200000 | 100000 | text+image | agents, agentsV2, reasoning, tool-calling, streaming |
| `openai/text-embedding-3-large` | OpenAI | embeddings | 8191 | — | text | — |
| `openai/text-embedding-3-small` | OpenAI | embeddings | 8191 | — | text | — |
| `xai/grok-3` | xAI | custom | 131072 | 4096 | text | agentsV2 |
| `xai/grok-3-mini` | xAI | custom | 131072 | 4096 | text | agentsV2 |

</details>

## Trial methodology

- **Workload:** the action's real review prompt (system rule-catalogue + the project's **mart**
  models), batched exactly as in production (greedy, under the ~8000-token request cap).
- **Per model captured:** `response_format` mode accepted, API call count (= batches), input/output
  tokens (summed across batches), wall-clock seconds, and estimated cost (multiplier × $10).
- **`response_format` ladder:** each model is tried `json_schema → json_object → plain`; the
  column records which it accepted (not all GitHub-hosted models support strict `json_schema`).
- **Caveats:** numbers reflect the free tier on the trial date; latency varies with load, and a
  model's daily quota may have been partially consumed by other runs. Re-run with
  `GITHUB_TOKEN=$(gh auth token) uv run --no-project --directory . benchmarks/bench.py`.

## Empirical results

<!-- BENCH_RESULTS -->
Trial date **2026-06-03** (free tier). Workload: review the **7 mart models** (`customers,
locations, metricflow_time_spine, order_items, orders, products, supplies`), batched as in
production. `calls` = request batches; `Tok/s` = output tokens ÷ wall (generation throughput);
tier/context from the catalogue. Run `bench.py` with `BENCH_SET=priced|newest`.

#### Priced set (cheapest-first)

| Model | tier | ctx in | resp_format | calls | In tok | Out tok | Wall (s) | Tok/s | Est. cost | Notes |
|-------|:----:|-------:|:-----------:|:-----:|------:|-------:|--------:|------:|----------:|-------|
| `microsoft/phi-4-mini-instruct` | low | 128,000 | plain | 3 | 5,269 | 1,154 | 293.9 | 3.9 | $0.0007 | ✓ (plain only) |
| `microsoft/phi-4` | low | 16,384 | json_object | 3 | 11,969 | 5,301 | 397.9 | 13.3 | $0.0041 | ✓ |
| `openai/gpt-4o-mini` | low | 131,072 | json_schema | 3 | 13,663 | 3,601 | 82.7 | 43.5 | $0.0042 | ✓ |
| `meta/llama-3.3-70b-instruct` | high | 128,000 | json_schema | 3 | 12,041 | 7,096 | 54.2 | 130.9 | $0.0136 | ✓ fastest non-OpenAI |
| `openai/gpt-4.1-mini` | low | 1,048,576 | json_schema | 3 | 13,663 | 8,003 | 139.7 | 57.3 | $0.0183 | ✓ |
| `meta/llama-4-maverick-17b-128e-instruct-fp8` | high | 1,000,000 | json_schema | 3 | 11,921 | 18,818 | 198.6 | 94.8 | $0.0218 | ✓ verbose output |
| `openai/gpt-4o` | high | 131,072 | json_schema | 3 | 13,663 | 2,472 | 37.3 | 66.3 | $0.0589 | ✓ fastest wall |
| `deepseek/deepseek-v3-0324` | high | 128,000 | json_object | 1/3 | 3,840 | 3,045 | 38.0 | 80.1 | partial | ⚠️ 413 — 4000-tok request cap |
| `xai/grok-3-mini` | custom | 131,072 | — | 0 | — | — | 3.7 | — | — | ⚠️ 400 `unknown_model` |
| `xai/grok-3` | custom | 131,072 | — | 0 | — | — | 3.6 | — | — | ⚠️ 400 `unknown_model` |

#### Newest set (8 newest/flagship; throughput-first — most are unpriced)

| Model | tier | ctx in | resp_format | calls | In tok | Out tok | Wall (s) | Tok/s | Est. cost | Notes |
|-------|:----:|-------:|:-----------:|:-----:|------:|-------:|--------:|------:|----------:|-------|
| `openai/gpt-5-nano` | custom | 200,000 | json_object | 1/3 | 3,733 | 16,752 | 142.7 | **117.4** | — | ⚠️ 413 4000-tok cap; unpriced; very verbose |
| `openai/o4-mini` | custom | 200,000 | json_object | 1/3 | 3,733 | 8,912 | 87.4 | 102.0 | — | ⚠️ 413 4000-tok cap; unpriced |
| `openai/o3` | custom | 200,000 | plain | 2/3 | 7,593 | 11,987 | 118.2 | 101.4 | — | ⚠️ 413 4000-tok cap; unpriced |
| `openai/gpt-5-mini` | custom | 200,000 | json_object | 1/3 | 3,733 | 6,849 | 99.7 | 68.7 | — | ⚠️ 413 4000-tok cap; unpriced |
| `meta/llama-4-scout-17b-16e-instruct` | high | 10,000,000 | json_schema | 3 | 11,921 | 3,795 | 56.8 | 66.8 | — | ✓ full run; unpriced |
| `deepseek/deepseek-r1-0528` | custom | 128,000 | json_object | 1/3 | 3,840 | 9,230 | 172.9 | 53.4 | $0.0550 | ⚠️ 413 4000-tok cap; **priced** |
| `openai/gpt-5` | custom | 200,000 | plain | 1/3 | 3,733 | 9,878 | 428.5 | 23.1 | — | ⚠️ 413 4000-tok cap; unpriced; slowest |
| `xai/grok-3` | custom | 131,072 | — | 0 | — | — | 4.1 | — | — | ⚠️ 400 `unknown_model` |

### Findings

- **Best default — `openai/gpt-4o-mini`**: native `json_schema`, **$0.0042** (≈14× cheaper than
  `gpt-4o`'s $0.0589 for the same work), 44 tok/s, fits the 8000-tok batch budget. Balanced winner.
- **Throughput ≠ cost ≠ wall.** Fastest *generators*: `gpt-5-nano` (117 tok/s), `o4-mini`/`o3`
  (~102), `llama-3.3-70b` (131 among priced). Fastest *wall*: `gpt-4o` (37 s). Cheapest:
  `phi-4-mini` ($0.0007, but plain-only and only 4 tok/s). Different winners per axis.
- **The newest reasoning models hit a 4000-token request cap** (free-tier `custom` tier — half of
  gpt-4o/4.1's 8000), so the action's 7000-tok budget 413s them after the first batch. To use them,
  drop `REQUEST_TOKEN_CAP` to ≤ ~3000 (ideally per-model). `deepseek-v3` shares this 4000 cap.
- **`temperature=0` is rejected by gpt-5/o-series** ("only the default is supported"); the engine now
  retries without it (ADR-8). Without that fix they 400 outright.
- **Most newest models are UNPRICED** — only `deepseek-r1-0528` has a published multiplier
  ($0.0550 here); `gpt-5*`, `o3`, `o4-mini`, `llama-4-scout` have none, so cost reads `—`.
- **Reasoning models are verbose + slow** — `gpt-5-nano` emitted **16.7k** output tokens; `gpt-5`
  took **428 s**. High output-token counts would dominate cost if/when these get priced.
- **`xai/grok-3*` is catalogued but not inferenceable** (`unknown_model`) — catalogue ≠ availability.
- **Structured output beyond OpenAI** — `llama-3.3-70b` and `llama-4-scout` accept strict
  `json_schema`; gpt-5/o-series accepted only `json_object`/plain here; Phi models only plain.

> **Recommendation:** keep the action default at **`openai/gpt-4o-mini`** — priced, structured
> (`json_schema`), 8000-tok cap fits the batch budget, balanced cost/throughput. The newest
> reasoning models are unpriced, slower, verbose, and 4000-tok-capped → poor fit as the default
> (and `cost-per-1m-*` can't be set meaningfully until GitHub publishes their multipliers). Re-run
> `bench.py` periodically — rates, availability, and caps change.
<!-- /BENCH_RESULTS -->
