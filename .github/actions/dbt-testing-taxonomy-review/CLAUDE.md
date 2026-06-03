# CLAUDE.md — maintainer decision lens

**Read the ADR log first.** Each ADR records *why* a thing is the way it is and carries a
**Lens** — a forward-looking rule to apply to the next related decision instead of re-deriving it.
This file never restates usage (that's [`README.md`](./README.md)) or the rule catalogue (that's
[`rules.json`](./rules.json)); it records rationale only.

## The development contract

Run from the repo root (never `cd`):

```bash
# 1. Engine syntax (stdlib-only; no install needed)
uv run --no-project python -m py_compile .github/actions/dbt-testing-taxonomy-review/review.py
# 2. Catalogue ↔ schema enum can't drift
diff <(jq -r '.rules[].code' .github/actions/dbt-testing-taxonomy-review/rules.json | sort) \
     <(jq -r '.properties.models.items.properties.findings.items.properties.rule_code.enum[]' \
          .github/actions/dbt-testing-taxonomy-review/review-output.schema.json | sort)
# 3. Lint the workflow that uses the action (if actionlint is available)
actionlint .github/workflows/testing-taxonomy-review.yml
# 4. Real behaviour: open a PR touching a model, or run the model trials
GITHUB_TOKEN=$(gh auth token) uv run --no-project --directory . \
  .github/actions/dbt-testing-taxonomy-review/benchmarks/bench.py
```

Steps 1–2 must be clean before handoff. The engine has **no unit tests by design** (it's an I/O
shell over an LLM + the GitHub API); correctness is proven by a live PR run, not mocks.

## File map

| File | Role |
|------|------|
| `action.yml` | Composite action: inputs → env → `setup-uv` → run `review.py` via `${{ github.action_path }}`. |
| `review.py` | Engine: diff changed models, batch, call GitHub Models (json_schema), render matrices, upsert comments, write usage summary. Stdlib-only. |
| `rules.json` | Single source of truth: 29 rule codes + metadata. |
| `review-output.schema.json` | Structured-output contract; its `rule_code` enum is overwritten from `rules.json` at runtime. |
| `README.md` | Human consumer docs (usage, diagram, reference). |
| `benchmarks/bench.py` · `benchmarks/MODELS.md` | Model trials + curated GitHub Models pricing/results. |

## Architecture principles (invariants a change must preserve)

- **Stdlib-only engine.** `review.py` imports nothing outside the standard library so
  `uv run --no-project` needs no network install on a runner. Don't add `requests`/SDKs.
- **Data loads relative to `__file__`.** `rules.json`/schema are read from the engine's own dir,
  which is `${{ github.action_path }}` — keeps the action relocatable. Don't hard-code repo paths.
- **Keyless.** The only credential is the workflow `GITHUB_TOKEN` (an input). Never add a vendor
  API-key secret.
- **`rules.json` is the source of truth.** The schema enum and prompt catalogue both derive from it.

## ADR log

### ADR-1 · LLM runner = GitHub Models (keyless), not a vendor API
**Status** accepted · **Context** the review needs an LLM in CI; the repo is WIF/keyless and
secrets-averse, and the maintainer explicitly barred Anthropic/OpenAI/Codex plugins and vendor
keys. **Decision** call GitHub Models at `models.github.ai/inference` with the built-in
`GITHUB_TOKEN` + `permissions: models: read`. **Consequences** zero secrets; subject to free-tier
rate/size limits (see ADR-5). **Lens** *for any CI LLM need here, reach for GitHub Models +
`GITHUB_TOKEN` first; a vendor key is a last resort that must be justified against the keyless value.*

### ADR-2 · A composite action, not an agent skill
**Status** accepted (superseded the original `.agents/skills/` location) · **Context** the tooling
began as a skill, but it is CI execution machinery, not an interactive agent capability.
**Decision** ship it as `.github/actions/dbt-testing-taxonomy-review/` (matches `.github/actions/terraform`);
docs follow `reusable-actions-docs.md` (README + CLAUDE.md, **no SKILL.md**). **Consequences** the
workflow is a thin `uses:`; agents still read `rules.json`/README for the framework. **Lens**
*executable CI logic → a composite action; an interactive capability an agent invokes → a skill.
If you want a SKILL.md on an action, the logic is in the wrong place.*

### ADR-3 · Rule codes encode role hierarchy only
**Status** accepted · **Context** needed stable, sortable codes; the maintainer wanted role
hierarchy (esp. `time` sub-roles) but the taxonomy also has orthogonal overlays (Wang–Strong, cost).
**Decision** `<ROLE>[-<SUBROLE>]-<NN>` — role/sub-role only; overlays stay as `rules.json` columns.
**Consequences** codes are stable even if a vignette's cost class changes. **Lens** *put only the
*stable* classifying axis in an ID; axes that vary independently or over time belong in columns.*

### ADR-4 · Schema enum injected from rules.json at runtime
**Status** accepted · **Context** two copies of the code list (catalogue + schema enum) would drift.
**Decision** the engine overwrites the schema's `rule_code` enum from `rules.json` before each call.
**Consequences** add a rule in one place. **Lens** *never maintain the same enumerated set in two
files; derive one from the other at runtime and keep a CI diff as the guard.*

### ADR-5 · Review-all-once + batch under a measured token budget
**Status** accepted · **Context** GitHub Models caps a request at ~8000 tokens (one big batch
413'd) **and** rate-limits the free tier (per-model loop of 13 calls 429'd). **Decision** review
all models once via greedy batching sized as `7000 − overhead(system prompt + schema)` with a
conservative ~3-chars/token estimate; derive the changed subset by name; back off on 429 honouring
`Retry-After`. **Consequences** ~4 calls for the project; both ceilings respected; the two matrices
stay consistent. **Lens** *when a per-item LLM loop trips a rate limit, batch items under a measured
token budget (accounting for fixed prompt+schema overhead) before adding more retries — fewer
requests beats more backoff; size the budget against the cap minus measured overhead, never a guess.*

### ADR-6 · Output is a coverage matrix; failures-only variants retired
**Status** accepted (trimmed from four variants to two) · **Context** four comment variants were
posted to compare formats; the maintainer chose the two coverage matrices (changed + all).
**Decision** post only `matrix-changed` + `matrix-all`; delete lingering `ttr:fails-*` comments on
each run. **Consequences** fewer comments; `delete_retired_comments` keeps PRs tidy after the trim.
**Lens** *when retiring a sticky-comment variant, delete its marker's comments on the next run —
don't leave orphans; markers make this safe and idempotent.*

### ADR-7 · Cost is reported, not enforced
**Status** accepted · **Context** the maintainer wanted token/cost visibility. **Decision** sum
`usage` across batches; estimate cost via configurable `cost-per-1m-*` inputs (default = GitHub
Models gpt-4o multipliers × $10); print to the comment footer, job summary, and log. **Consequences**
advisory; the free tier may bill $0, so the figure is an at-list-price comparison. **Lens** *surface
cost from the provider's own `usage` payload + its published multipliers; keep rates as inputs so a
model swap re-prices without code changes.*

## Extension checklist

- [ ] Adding a rule? Edit `rules.json` only (code + metadata + `doc`); the schema enum follows automatically. Run the dev-contract diff.
- [ ] New comment variant? Give it a unique `<!-- ttr:* -->` marker; add to `MARKERS`; render + `upsert_comment`; if replacing one, add the old marker to `RETIRED_MARKERS`.
- [ ] New input? Add to `action.yml` (description + default) **and** map it to env in the run step **and** read it via `env()` in `review.py`. Document it in `README.md`.
- [ ] Changed the engine's request shape? Re-confirm the batch budget still clears the token cap (ADR-5) with a live PR run.
- [ ] Touched the README diagram? Re-run `mermaid_contrast.ts` + `mermaid_complexity.ts` (both exit 0).

## Known gotchas

- **`413 tokens_limit_reached`** even with batching — the estimate under-counted or ignored the
  fixed overhead (system prompt **+ the response_format schema both count as input**). Lower the
  budget; the estimate is deliberately conservative (~3 chars/token).
- **`429` mid-run** — free-tier per-minute *and* per-day limits exist; repeated local/CI runs in a
  day can exhaust a model's daily quota. Backoff handles bursts, not an exhausted daily cap.
- **Fork PRs** — `GITHUB_TOKEN` is read-only and lacks `models:` there; the workflow `if:` gates to
  same-repo PRs so failures are real errors, not permission noise.
- **Non-OpenAI models + `json_schema`** — not all GitHub Models support strict `json_schema`; a
  `400` on `response_format` means the model needs a json_object/plain fallback (see `benchmarks/bench.py`).
- **`uv run --no-project`** is required — without it `uv` looks for a project and the action dir has none.
