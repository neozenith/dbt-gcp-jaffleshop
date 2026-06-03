# GitHub-hosted models — pricing & empirical trials

Reference for choosing the `model` input of the
[`dbt-testing-taxonomy-review`](../README.md) action:

1. **Pricing & rate limits** — the GitHub Models catalogue, GitHub's cost multipliers, and the
   free-tier rate limits + per-request token caps (all from authoritative GitHub sources).
2. **Empirical trials** — real token / pure-request-latency / true-throughput / cost measurements
   running ONE standardised review request against a provider-diverse set of models (via
   [`bench.py`](./bench.py)).

## Canonical model table — all sources joined

**👉 The single joined table is [`canonical.md`](./canonical.md)** — all **39 chat models**
(embeddings + Grok excluded) `LEFT JOIN`ed with pricing (**13 priced**) and benchmark results
(**19 trialled**), including a **Findings** completeness column. It's **generated** by
[`join.py`](./join.py) (live catalogue + multipliers + the `results-*.md` bench outputs):

```bash
GITHUB_TOKEN=$(gh auth token) uv run --no-project \
  .github/actions/dbt-testing-taxonomy-review/benchmarks/join.py
```

`—` = not priced / not benchmarked. **Always read `cost`/`tok/s` alongside `findings`** — a model
that emitted few findings under-reviewed, so its "cheap/fast" is not real value (see [Findings](#findings--corrected-with-a-completeness-signal)).
The sections below are the source breakdowns that feed the canonical table.

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
<summary>39 chat models — GHA-extracted 2026-06-03 (run 26883567820); <code>xai/grok-3</code>/<code>-mini</code> (unknown_model) and the 2 <code>text-embedding-3-*</code> models (not chat) omitted</summary>

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

## Findings — corrected with a completeness signal

Numbers are from the standardised **one-request `locations` review** (pure request latency; rate-limit
waits excluded; full per-model data in [`canonical.md`](./canonical.md)). **Output volume varies
hugely, so cost and tok/s are only comparable at similar completeness** — hence the `findings` count
(parsed from each response), which reframes the comparison as *cost per actual review*.

- **`gpt-4o-mini` under-reviewed — 8 findings** vs `gpt-4o` / `gpt-4.1` / `llama-4-maverick` at **29**.
  It looked "cheapest/fastest" only because it did ~¼ of the work — not real value.
- **Best value (priced): `meta/llama-4-maverick-17b-128e-instruct-fp8`** — **29 findings at $0.0026**,
  same completeness as `gpt-4o` ($0.0222) for ~9× less, `json_schema`, ~100 tok/s. Runner-up:
  `gpt-4.1-mini` (26 findings, $0.0038).
- **Most complete (priced): `gpt-4o` / `gpt-4.1`** (29 findings) — thorough but priciest (~$0.022–0.023).
- **Zero-findings — do NOT use for this task.** `phi-4`, `phi-4-mini-instruct` (json_object) and,
  more worryingly, `llama-3.3-70b` + `deepseek-v3-0324` (strict `json_schema`) returned **0 findings** —
  structurally-valid-but-empty / wrong-shaped output. Cheap and fast, but they didn't actually review.
- **Unverifiable (findings `—`): the DeepSeek-R1 reasoners** returned content that didn't parse as the
  review JSON (reasoning prose / fences), so completeness can't be confirmed; `deepseek-r1-0528` is
  also the priciest priced run (~$0.034–0.045).
- **Newest set (unpriced) is capable but throttled.** `llama-4-scout` **53 findings** (most thorough),
  `gpt-5-mini` / `o3` **33**, `gpt-5-nano` 28 — all genuine reviews. But `custom`-tier rate limits bite:
  `gpt-5` failed outright (**429** after 12 retries / 390 s wait), and none are priced.
- **Consistency caveat.** `temperature=0` (non-reasoning) is ~reproducible run-to-run; reasoning
  models (gpt-5/o-series, temp=1) vary. Counts are single-run — treat ±a few findings as noise.

> **Recommendation (revised):** make the action default **`meta/llama-4-maverick-17b-128e-instruct-fp8`**
> — a full 29-finding review at $0.0026, `json_schema`, high-tier (8000-in cap) — **not** `gpt-4o-mini`,
> which under-reviews. Escalate to `gpt-4o`/`gpt-4.1` only when maximum completeness justifies ~10× cost.
> Avoid the 0-finding models. Re-run `bench.py` then `join.py` to refresh — **findings is the quality gate.**

> **Parser caveat.** `findings` counts entries in the `{ "models": [ { "findings": [] } ] }` shape.
> A `0` from a json_object/plain model may be a *shape* mismatch (findings produced differently);
> a `0` from a strict-`json_schema` model is a genuine empty review; `—` = response didn't parse as JSON.
