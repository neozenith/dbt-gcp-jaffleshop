# `adaf` — Automated Data Assurance Framework

One CLI over the dbt **testing-taxonomy catalogue**. The catalogue
([`src/adaf/rules/catalog.json`](src/adaf/rules/catalog.json)) is the single
source of truth for the 33 data-quality rules; every consumer — the deterministic
checks, the LLM review, the docs, and the developer skill — derives from it so
nothing can drift. See
[ADR-0005](../../../docs/arch/adr-0005-adaf-automated-data-assurance-framework.md)
for why this exists and [`CLAUDE.md`](CLAUDE.md) for how to extend it.

## Install / run

`adaf` is an installable `uv` tool (same shape as `infra/tfs/`). From the repo root:

```bash
# Run without installing (CI + local dev) — uv builds the project env on demand
uv run --directory .github/cli/adaf adaf rules validate
uv run --frozen --directory .github/cli/adaf adaf rules list --detection deterministic

# Or install once so `adaf` is on PATH anywhere
uv tool install '.github/cli/adaf'
adaf rules show MD-01
```

## Commands

Two scoping models coexist (see [`CLAUDE.md`](CLAUDE.md)). The **`check`** gates
scope by **changed files** (default) or `--all`, narrowed by inline dbt
`--select`/`--exclude`. The **data-product** commands (`list`, `defer-*`,
`sdag check`) scope by a **named `--selector`** from `selectors.yml`, optionally
grown along the lineage with `--upstream`/`--downstream`.

### Inspect the catalogue (no dbt project needed)

| Command | What it does |
|---------|--------------|
| `adaf rules list [--role/--detection/--dama] [--json]` | List catalogue rules, filterable by role, detection mode, or DAMA-UK6 dimension. |
| `adaf rules show <code> [--json]` | One rule in full — both DQ attributions, detection mode, boundary class, framework ladder, vignette path. |
| `adaf rules explain <code> [--json]` | `show` plus the exact `adaf.yml` / inline syntax to suppress the rule. |
| `adaf rules validate` | Validate `catalog.json` against its meta-schema; non-zero exit on any violation (the SSoT guard). |

### Deterministic gates over the selected models

| Command | What it does |
|---------|--------------|
| `adaf check taxonomy [--strict]` | Run the deterministic catalogue detectors (grain/freshness/contracts/keys) over the selected models. |
| `adaf check docs` / `doc-columns` / `tests` | Model-description, resolved-column, and test coverage of the selected models (from the manifest / catalog). |
| `adaf check lint` / `format` `[--fix] [--commands]` | SQLFluff full ruleset / formatter subset; `--commands` prints the exact argv instead of running it. |
| `adaf check deprecations [--fix] [--commands]` | `dbt-autofix` over the folders of the selected models. |
| `adaf check system-boundaries` | Gate each inbound/outbound boundary node of a data product on its required artifacts. |
| `adaf check all [--fix --md <path>]` | Run every check; non-zero if any fail. `--md` writes a PR-comment summary table. |

### Data-product workflows (scoped by a named `--selector`)

| Command | What it does |
|---------|--------------|
| `adaf list` (alias `ls`) `[--upstream/--downstream] [--macros] [--paths] [--bare]` | Preview the resolved scope — the model files the gates would run on, grouped by selector/upstream/downstream. |
| `adaf sdag check` | Boundary-obligation lint: outbound models owe a contract (MD-02), exposure (MD-11), semantic model (MD-12); inbound sources owe freshness (TM-AU-01) + a volume-anomaly test (MD-07). |
| `adaf defer-diff [--details]` | Which models in scope would be **built** vs **deferred** against a `--defer-ref` baseline, with deepdiff explaining each rebuild. |
| `adaf defer-state [--force]` | Build (or reuse) the defer-target state for a ref and print its `--state` dir on stdout (CI plumbing). |
| `adaf products boundaries` / `generate` / `serve` | Classify a product's nodes; build / host the interactive sdag Cytoscape viewer (`--inline`, `--archive`). |
| `adaf gha create` / `update` / `analyse` | Generate / refresh / analyse a per-data-product GHA workflow whose trigger `paths` are derived from the selector. |

### LLM review + reconciliation

| Command | What it does |
|---------|--------------|
| `adaf review [--post] [--model ...]` | LLM taxonomy review via GitHub Models (keyless); `--post` upserts sticky PR comments. |
| `adaf report [--review <json>] [-o <file>]` | Per-model markdown; with `--review`, reconciles the LLM findings against the deterministic ground truth. |

## Data-quality attribution

Every rule carries **two** attributions:

- **`dama`** — the [DAMA-UK six primary dimensions](https://www.dama.org)
  (Completeness, Uniqueness, Timeliness, Validity, Accuracy, Consistency). The
  primary, operational lens.
- **`wang_strong`** — the genuine Wang & Strong (1996) dimensions, the secondary
  consumer-perception lens, derived via a documented crosswalk in the catalogue.

## For maintainers

See [`CLAUDE.md`](CLAUDE.md) — the development contract, the SSoT invariants a
change must preserve, and the extension checklist.
