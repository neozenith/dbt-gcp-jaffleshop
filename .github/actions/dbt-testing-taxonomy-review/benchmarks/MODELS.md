# GitHub-hosted models — pricing & empirical trials

Reference for choosing the `model` input of the
[`dbt-testing-taxonomy-review`](../README.md) action:

1. **Pricing & rate limits** — the GitHub Models catalogue, GitHub's cost multipliers, and the
   free-tier rate limits + per-request token caps (all from authoritative GitHub sources).
2. **Empirical trials** — real token / pure-request-latency / true-throughput / cost measurements
   running ONE standardised review request against a provider-diverse set of models (via
   [`bench.py`](./bench.py)).

> **👉 The one table is right below.** Everything is `LEFT JOIN`ed per model there; the sections
> after it (billing, rate limits, full catalogue, per-set results) are the source breakdowns.

## Canonical model table — all sources joined

The single source of truth: every catalogue model `LEFT JOIN`ed with pricing and benchmark results.
**Generated** by [`join.py`](./join.py) (live catalogue + embedded multipliers + the `results-*.md`
bench outputs) — regenerate with `GITHUB_TOKEN=$(gh auth token) uv run --no-project .github/actions/dbt-testing-taxonomy-review/benchmarks/join.py`.
`—` = not priced / not benchmarked.

Canonical table — 41 catalogue models LEFT-JOINed with pricing (13 priced) and benchmark results (15 trialled). Grok excluded (`unknown_model`).

| Model | Provider | Tier | Ctx in | Input modes | $/1M in | $/1M out | Bench resp_format | Bench out tok | Bench req (s) | Bench tok/s | Bench cost | Bench status |
|---|---|:--:|--:|---|--:|--:|:--:|--:|--:|--:|--:|---|
| `ai21-labs/ai21-jamba-1.5-large` | AI21 Labs | high | 262,144 | text | — | — | — | — | — | — | — | — |
| `cohere/cohere-command-a` | Cohere | low | 131,072 | text | — | — | — | — | — | — | — | — |
| `cohere/cohere-command-r-08-2024` | Cohere | low | 131,072 | text | — | — | — | — | — | — | — | — |
| `cohere/cohere-command-r-plus-08-2024` | Cohere | high | 131,072 | text | — | — | — | — | — | — | — | — |
| `deepseek/deepseek-r1` | DeepSeek | custom | 128,000 | text | $1.35 | $5.40 | — | — | — | — | — | — |
| `deepseek/deepseek-r1-0528` | DeepSeek | custom | 128,000 | text | $1.35 | $5.40 | json_schema | 4,770 | 47.3 | 100.8 | $0.0291 | ✓ |
| `deepseek/deepseek-v3-0324` | DeepSeek | high | 128,000 | text | $1.14 | $4.56 | json_schema | 1,008 | 9.6 | 105.0 | $0.0075 | ✓ |
| `meta/llama-3.2-11b-vision-instruct` | Meta | low | 128,000 | text+image+audio | — | — | — | — | — | — | — | — |
| `meta/llama-3.2-90b-vision-instruct` | Meta | high | 128,000 | text+image+audio | — | — | — | — | — | — | — | — |
| `meta/llama-3.3-70b-instruct` | Meta | high | 128,000 | text | $0.71 | $0.71 | json_schema | 1,725 | 35.7 | 48.3 | $0.0030 | ✓ |
| `meta/llama-4-maverick-17b-128e-instruct-fp8` | Meta | high | 1,000,000 | text+image | $0.25 | $1.00 | json_schema | 1,987 | 21.0 | 94.6 | $0.0026 | ✓ |
| `meta/llama-4-scout-17b-16e-instruct` | Meta | high | 10,000,000 | text+image | — | — | json_schema | 2,105 | 19.5 | 107.9 | — | ✓ |
| `meta/meta-llama-3.1-405b-instruct` | Meta | high | 131,072 | text | — | — | — | — | — | — | — | — |
| `meta/meta-llama-3.1-8b-instruct` | Meta | low | 131,072 | text | — | — | — | — | — | — | — | — |
| `microsoft/mai-ds-r1` | Microsoft | custom | 128,000 | text | $1.35 | $5.40 | — | — | — | — | — | — |
| `microsoft/phi-4` | Microsoft | low | 16,384 | text | $0.13 | $0.50 | json_object | 664 | 20.5 | 32.4 | $0.0006 | ✓ |
| `microsoft/phi-4-mini-instruct` | Microsoft | low | 128,000 | text | $0.08 | $0.30 | json_object | 91 | 5.6 | 16.2 | $0.0000 | ✓ |
| `microsoft/phi-4-mini-reasoning` | Microsoft | low | 128,000 | text | — | — | — | — | — | — | — | — |
| `microsoft/phi-4-multimodal-instruct` | Microsoft | low | 128,000 | audio+image+text | $0.08 | $0.32 | — | — | — | — | — | — |
| `microsoft/phi-4-reasoning` | Microsoft | low | 32,768 | text | — | — | — | — | — | — | — | — |
| `mistral-ai/codestral-2501` | Mistral AI | low | 256,000 | text | — | — | — | — | — | — | — | — |
| `mistral-ai/ministral-3b` | Mistral AI | low | 131,072 | text | — | — | — | — | — | — | — | — |
| `mistral-ai/mistral-medium-2505` | Mistral AI | low | 128,000 | text+image | — | — | — | — | — | — | — | — |
| `mistral-ai/mistral-small-2503` | Mistral AI | low | 128,000 | text+image | — | — | — | — | — | — | — | — |
| `openai/gpt-4.1` | OpenAI | high | 1,048,576 | text+image | $2.00 | $8.00 | — | — | — | — | — | — |
| `openai/gpt-4.1-mini` | OpenAI | low | 1,048,576 | text+image | $0.40 | $1.60 | json_schema | 1,341 | 16.5 | 81.3 | $0.0034 | ✓ |
| `openai/gpt-4.1-nano` | OpenAI | low | 1,048,576 | text+image | — | — | — | — | — | — | — | — |
| `openai/gpt-4o` | OpenAI | high | 131,072 | text+image+audio | $2.50 | $10.00 | json_schema | 1,409 | 9.7 | 145.3 | $0.0217 | ✓ |
| `openai/gpt-4o-mini` | OpenAI | low | 131,072 | text+image+audio | $0.15 | $0.60 | json_schema | 299 | 5.3 | 56.4 | $0.0006 | ✓ |
| `openai/gpt-5` | OpenAI | custom | 200,000 | text+image | — | — | json_schema | 7,668 | 158.5 | 48.4 | — | ✓ |
| `openai/gpt-5-chat` | OpenAI | custom | 200,000 | text+image | — | — | — | — | — | — | — | — |
| `openai/gpt-5-mini` | OpenAI | custom | 200,000 | text+image | — | — | json_schema | 5,084 | 67.8 | 75.0 | — | ✓ |
| `openai/gpt-5-nano` | OpenAI | custom | 200,000 | text+image | — | — | json_schema | 7,577 | 85.3 | 88.8 | — | ✓ |
| `openai/o1` | OpenAI | custom | 200,000 | text+image | — | — | — | — | — | — | — | — |
| `openai/o1-mini` | OpenAI | custom | 128,000 | text | — | — | — | — | — | — | — | — |
| `openai/o1-preview` | OpenAI | custom | 128,000 | text | — | — | — | — | — | — | — | — |
| `openai/o3` | OpenAI | custom | 200,000 | text+image | — | — | json_schema | 3,563 | 28.6 | 124.6 | — | ✓ |
| `openai/o3-mini` | OpenAI | custom | 200,000 | text | — | — | — | — | — | — | — | — |
| `openai/o4-mini` | OpenAI | custom | 200,000 | text+image | — | — | json_schema | 6,112 | 43.3 | 141.2 | — | ✓ |
| `openai/text-embedding-3-large` | OpenAI | embeddings | 8,191 | text | — | — | — | — | — | — | — | — |
| `openai/text-embedding-3-small` | OpenAI | embeddings | 8,191 | text | — | — | — | — | — | — | — | — |

---

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
| **Custom** (per-model; reasoning, gpt-5/o*, deepseek) | model-specific & much tighter (e.g. `o1-preview` = 1 rpm) | — | observed **4000 in** | — |

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
| `meta/llama-4-maverick-17b-128e-instruct-fp8` | Meta | 0.025 | — | 0.1 | $0.25 | — | $1.00 |
| `meta/llama-3.3-70b-instruct` | Meta | 0.071 | — | 0.071 | $0.71 | — | $0.71 |

> GitHub publishes multipliers for 15 models; the 2 Grok ids (`xai/grok-3`, `xai/grok-3-mini`) are
> **omitted everywhere** in this doc because they return `unknown_model` at the inference endpoint
> (priced but not usable), leaving the 13 shown. The other ~26 catalogue entries (Cohere, Mistral
> AI, AI21 Labs, the OpenAI `gpt-5`/`o`-series, `llama-4-scout`, …) are inferenceable but
> **unpriced** in the doc — so their at-list-price cost can't be stated, shown as `—` below.

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
<summary>41 models — GHA-extracted 2026-06-03 (run 26883567820); <code>xai/grok-3</code>/<code>-mini</code> omitted (return unknown_model)</summary>

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
Trial date **2026-06-03** (free tier). **Standardised example:** review the small `locations` mart
in **ONE request** (~3,000 input tokens — under the 4000 cap, so *every* model, including the
4000-capped reasoning models, completes it in a single request and is directly comparable).

- **`Req (s)`** = pure request latency (network + generation) — **excludes** rate-limit waits and
  inter-model spacing.
- **`Tok/s`** = output tokens ÷ `Req (s)` — **true** generation throughput (the prior wall-based
  figure was inflated by 429 backoff + batch spacing; this fixes that).
- **`429 retries (wait s)`** = rate-limit hits and the seconds spent waiting on them, tracked
  **separately** (not in `Req (s)`/`Tok/s`).

Run `bench.py` with `BENCH_SET=priced|newest`. Both tables sorted by true throughput.

#### Priced set (true-throughput-first)

| Model | tier | ctx in | resp_format | In tok | Out tok | Req (s) | Tok/s | 429 retries (wait s) | Est. cost | Notes |
|-------|:----:|-------:|:-----------:|------:|-------:|--------:|------:|:--------------------:|----------:|-------|
| `openai/gpt-4o` | high | 131,072 | json_schema | 3,042 | 1,409 | 9.7 | **145.3** | 0 | $0.0217 | ✓ priciest |
| `deepseek/deepseek-v3-0324` | high | 128,000 | json_schema | 2,511 | 1,008 | 9.6 | 105.0 | 0 | $0.0075 | ✓ |
| `meta/llama-4-maverick-17b-128e-instruct-fp8` | high | 1,000,000 | json_schema | 2,461 | 1,987 | 21.0 | 94.6 | 0 | $0.0026 | ✓ |
| `openai/gpt-4.1-mini` | low | 1,048,576 | json_schema | 3,042 | 1,341 | 16.5 | 81.3 | 0 | $0.0034 | ✓ |
| `openai/gpt-4o-mini` | low | 131,072 | json_schema | 3,042 | 299 | 5.3 | 56.4 | 0 | **$0.0006** | ✓ cheapest structured |
| `meta/llama-3.3-70b-instruct` | high | 128,000 | json_schema | 2,508 | 1,725 | 35.7 | 48.3 | 0 | $0.0030 | ✓ |
| `microsoft/phi-4` | low | 16,384 | json_object | 2,484 | 664 | 20.5 | 32.4 | 0 | $0.0006 | ✓ |
| `microsoft/phi-4-mini-instruct` | low | 128,000 | json_object | 244 | 91 | 5.6 | 16.2 | 0 | ~$0.0000 | ⚠️ in=244 (sparse/likely truncated) |

#### Newest set (7 newest/flagship; true-throughput-first — most unpriced)

All ran the standardised example in **one `json_schema` request** (the temperature fix + the small
example unblocked them). The reasoning models each ate **2–3 rate-limit retries / 60–70 s of wait**
on the free `custom` tier — excluded from `Req (s)`/`Tok/s` below.

| Model | tier | ctx in | resp_format | In tok | Out tok | Req (s) | Tok/s | 429 retries (wait s) | Est. cost | Notes |
|-------|:----:|-------:|:-----------:|------:|-------:|--------:|------:|:--------------------:|----------:|-------|
| `openai/o4-mini` | custom | 200,000 | json_schema | 3,038 | 6,112 | 43.3 | **141.2** | 3 (70.0) | — | ✓ unpriced |
| `openai/o3` | custom | 200,000 | json_schema | 3,038 | 3,563 | 28.6 | 124.6 | 0 | — | ✓ unpriced |
| `meta/llama-4-scout-17b-16e-instruct` | high | 10,000,000 | json_schema | 2,461 | 2,105 | 19.5 | 107.9 | 0 | — | ✓ unpriced |
| `deepseek/deepseek-r1-0528` | custom | 128,000 | json_schema | 2,511 | 4,770 | 47.3 | 100.8 | 3 (70.0) | $0.0291 | ✓ **priced** |
| `openai/gpt-5-nano` | custom | 200,000 | json_schema | 3,038 | 7,577 | 85.3 | 88.8 | 3 (70.0) | — | ✓ unpriced; verbose |
| `openai/gpt-5-mini` | custom | 200,000 | json_schema | 3,038 | 5,084 | 67.8 | 75.0 | 2 (60.0) | — | ✓ unpriced |
| `openai/gpt-5` | custom | 200,000 | json_schema | 3,038 | 7,668 | 158.5 | 48.4 | 3 (70.0) | — | ✓ unpriced; slowest |

### Findings (on the standardised `locations` example, corrected timing)

- **Throughput ≠ cost ≠ latency** (different winners per axis). True generation throughput:
  `gpt-4o` 145, `o4-mini` 141, `o3` 125, `llama-4-scout` 108, `deepseek-v3` 105 tok/s. Cheapest
  with structured output: **`gpt-4o-mini` & `phi-4` at $0.0006**. `gpt-4o` is fast *and* priciest
  ($0.0217). For this small example, `gpt-4o-mini` does the least work (out=299) → low cost.
- **Rate-limit wait is now separated from request time.** The newest `custom`-tier models each spent
  **60–70 s in 429 backoff** (2–3 retries) before a successful call — that wait is excluded, so
  their `Tok/s` reflects real generation speed. But for *wall-clock* CI cost, that backoff is real:
  custom-tier models are heavily throttled (very low rpm + 50-ish/day) → poor for routine PR review.
- **`json_schema` works broadly now** — at this size, gpt-5/o-series and `deepseek-r1` all accepted
  strict `json_schema` (earlier failures were the `temperature=0` 400, now auto-dropped — ADR-8).
  Only the **Phi** models fell back to `json_object`.
- **Per-request input cap bites the big models.** Reasoning/`custom`-tier models cap at **4000 input
  tokens**; the standardised `locations` request (~3,000 in) fits, but reviewing a *large* mart
  (`orders` ≈ 4,457 in) does **not** — so on a 4000-cap model the action must keep `REQUEST_TOKEN_CAP`
  ≤ ~3000 (and even then can't fit big models in one batch).
- **Most newest models are UNPRICED** — only `deepseek-r1-0528` has a multiplier ($0.0291 here);
  `gpt-5*`, `o3`, `o4-mini`, `llama-4-scout` show `—` (cost can't be stated until GitHub publishes
  multipliers).
- **Grok omitted** — `xai/grok-3` / `-mini` return `unknown_model` at the inference endpoint
  (catalogued and priced, but not usable), so they're excluded from every table here.
- **`phi-4-mini-instruct` anomaly** — reported `in=244` (vs ~2,500 for every other model on the same
  input) and a 91-token output; likely silent input truncation. Treat its numbers as unreliable.

> **Recommendation:** keep the action default at **`openai/gpt-4o-mini`** — priced ($0.0006 on this
> example), strict `json_schema`, *low* tier (150 req/day vs high tier's 50), 8000-tok cap fits the
> batch budget. The newest reasoning models are fast per-request but **unpriced, custom-tier
> rate-limited (60–70 s backoff/run here), and 4000-in-capped** → poor fit for routine CI. Re-run
> `bench.py` (`BENCH_SET=priced|newest`) periodically — rates, availability, and caps change.
<!-- /BENCH_RESULTS -->
