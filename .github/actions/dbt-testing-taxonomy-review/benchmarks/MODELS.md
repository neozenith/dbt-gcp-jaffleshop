# GitHub-hosted models — pricing & empirical trials

Reference for choosing the `model` input of the
[`dbt-testing-taxonomy-review`](../README.md) action. Two parts:

1. **Pricing** — the GitHub Models catalogue + GitHub's own cost multipliers.
2. **Empirical trials** — real token/call/latency/cost measurements running this action's
   review workload against a curated, provider-diverse set of models (via
   [`bench.py`](./bench.py)).

## How GitHub Models bills

GitHub Models charges **$0.00001 per token unit**. Token units = actual tokens × the model's
**multiplier** (separate input and output multipliers). So the at-list-price rate is:

```
$ / 1M tokens  =  multiplier × 1,000,000 × $0.00001  =  multiplier × $10
```

> The **free tier may bill $0** (rate-limited). The cost column below is the at-list-price
> equivalent, so models are comparable regardless of which tier actually runs them.
> Source: [Costs for GitHub Models](https://docs.github.com/en/billing/reference/costs-for-github-models) (fetched 2026-06-03).

## Catalogue + pricing (models with published multipliers)

| Model id | Provider | Input mult. | Output mult. | ≈ $/1M in | ≈ $/1M out |
|----------|----------|------------:|-------------:|----------:|-----------:|
| `openai/gpt-4o` | OpenAI | 0.25 | 1.0 | $2.50 | $10.00 |
| `openai/gpt-4o-mini` | OpenAI | 0.015 | 0.06 | $0.15 | $0.60 |
| `openai/gpt-4.1` | OpenAI | 0.2 | 0.8 | $2.00 | $8.00 |
| `openai/gpt-4.1-mini` | OpenAI | 0.04 | 0.16 | $0.40 | $1.60 |
| `microsoft/phi-4` | Microsoft | 0.0125 | 0.05 | $0.125 | $0.50 |
| `microsoft/phi-4-mini-instruct` | Microsoft | 0.0075 | 0.03 | $0.075 | $0.30 |
| `microsoft/phi-4-multimodal-instruct` | Microsoft | 0.008 | 0.032 | $0.08 | $0.32 |
| `deepseek/deepseek-v3-0324` | DeepSeek | 0.114 | 0.456 | $1.14 | $4.56 |
| `deepseek/deepseek-r1` | DeepSeek | 0.135 | 0.54 | $1.35 | $5.40 |
| `microsoft/mai-ds-r1` | Microsoft | 0.135 | 0.54 | $1.35 | $5.40 |
| `xai/grok-3` | xAI | 0.3 | 1.5 | $3.00 | $15.00 |
| `xai/grok-3-mini` | xAI | 0.025 | 0.127 | $0.25 | $1.27 |
| `meta/llama-3.3-70b-instruct` | Meta | 0.071 | 0.071 | $0.71 | $0.71 |
| `meta/llama-4-maverick-17b-128e-instruct-fp8` | Meta | 0.025 | 0.1 | $0.25 | $1.00 |

> Other catalogue families (Cohere, Mistral AI, AI21 Labs, OpenAI `gpt-5`/`o`-series) are
> available for inference but did **not** have published billing multipliers at fetch time, so
> their at-list-price cost can't be stated here.

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
locations, metricflow_time_spine, order_items, orders, products, supplies`), batched. Sorted
cheapest-first among successful runs; `API calls` = batches.

| Model | resp_format | API calls | Input tok | Output tok | Total tok | Wall (s) | Est. cost | Status |
|-------|:-----------:|:---------:|----------:|-----------:|----------:|---------:|----------:|--------|
| `microsoft/phi-4-mini-instruct` | plain | 3 | 5,269 | 1,154 | 6,423 | 293.9 | $0.0007 | ✓ |
| `microsoft/phi-4` | json_object | 3 | 11,969 | 5,301 | 17,270 | 397.9 | $0.0041 | ✓ |
| `openai/gpt-4o-mini` | json_schema | 3 | 13,663 | 3,601 | 17,264 | 82.7 | $0.0042 | ✓ |
| `meta/llama-3.3-70b-instruct` | json_schema | 3 | 12,041 | 7,096 | 19,137 | 54.2 | $0.0136 | ✓ |
| `openai/gpt-4.1-mini` | json_schema | 3 | 13,663 | 8,003 | 21,666 | 139.7 | $0.0183 | ✓ |
| `meta/llama-4-maverick-17b-128e-instruct-fp8` | json_schema | 3 | 11,921 | 18,818 | 30,739 | 198.6 | $0.0218 | ✓ |
| `openai/gpt-4o` | json_schema | 3 | 13,663 | 2,472 | 16,135 | 37.3 | $0.0589 | ✓ |
| `deepseek/deepseek-v3-0324` | json_object | 1 of 3 | 3,840 | 3,045 | 6,885 | 38.0 | partial | ⚠️ 413 — per-model cap is **4000 tok** (< 8000); later batches overflow |
| `xai/grok-3-mini` | — | 0 | — | — | — | 3.7 | — | ⚠️ 400 `unknown_model` — not available for inference on this account |
| `xai/grok-3` | — | 0 | — | — | — | 3.6 | — | ⚠️ 400 `unknown_model` |

### Findings

- **Best default — `openai/gpt-4o-mini`**: native `json_schema`, **$0.0042** (≈14× cheaper than
  `gpt-4o`'s $0.0589 for the same work), ~83 s. Strong balance of cost, speed, and structure.
- **Fastest — `openai/gpt-4o`** (37 s) but the most expensive by far; reserve for max-quality needs.
- **Cheapest — `microsoft/phi-4-mini-instruct`** ($0.0007) but only in **plain** mode (it rejected
  both `json_schema` and `json_object`), so it relies on prompt-only JSON — riskier for the strict
  contract. `microsoft/phi-4` ($0.0041, `json_object`) is the cheap-but-structured middle.
- **Non-OpenAI structured output works** — `meta/llama-3.3-70b-instruct` accepted `json_schema`
  ($0.0136, fastest non-OpenAI at 54 s).
- **Output verbosity drives cost** — `llama-4-maverick` emitted **18.8k** output tokens (vs gpt-4o's
  2.5k), making it slower and pricier than its low rate suggests.
- **Per-model request caps differ** — `deepseek-v3-0324` caps requests at **4000 tokens** (half of
  gpt-4o's 8000); the engine's fixed 7000 budget overflows it. To use a small-cap model, lower
  `REQUEST_TOKEN_CAP` (ideally make the budget per-model).
- **Catalogue ≠ inference availability** — `xai/grok-3*` are listed in the catalogue but return
  `unknown_model` at the inference endpoint; verify a model answers before adopting it.
- **Throughput varies** — the Phi models were slow on the free tier (~300–400 s); OpenAI + Llama
  returned in 40–140 s.

> **Recommendation:** default the action to **`openai/gpt-4o-mini`** (`model` input) — structured,
> cheap, fast-enough. Keep `gpt-4o` as a quality escalation. Re-run `bench.py` periodically; rates
> and availability change.
<!-- /BENCH_RESULTS -->
