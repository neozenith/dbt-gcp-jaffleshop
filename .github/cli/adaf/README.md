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

| Command | What it does |
|---------|--------------|
| `adaf rules list [--role/--detection/--dama] [--json]` | List catalogue rules, filterable by role, detection mode, or DAMA-UK6 dimension. |
| `adaf rules show <code> [--json]` | One rule in full — both DQ attributions, detection mode, boundary class, framework ladder, vignette path. |
| `adaf rules validate` | Validate `catalog.json` against its meta-schema; non-zero exit on any violation (the SSoT guard). |

> The `check`, `review`, and `products` command groups are added as the ADAF
> build-out migrates the deterministic checker and the LLM reviewer in. This
> README's reference table and architecture diagram are completed in the docs
> consolidation pass.

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
