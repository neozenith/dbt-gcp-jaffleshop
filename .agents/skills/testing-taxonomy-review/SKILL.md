---
name: testing-taxonomy-review
description: >-
  Reviews dbt models against this project's testing taxonomy using stable rule
  codes (EN-/DM-/MS-/TM-/MD-). Use when reviewing a PR's added or changed dbt
  models for test-coverage gaps, deciding which data tests a column or model
  needs, or triaging a data-quality incident by symptom. Curates the rule
  catalogue, a one-line summary per code, and a decision framework for which
  rules apply when.
allowed-tools: "Read, Glob, Grep, Bash(dbt *), Bash(jq *)"
user-invocable: true
metadata:
  author: play-dbt-gcp-jaffleshop
  source: docs/guides/testing_taxonomy/
  catalogue: .agents/skills/testing-taxonomy-review/rules.json
  output_schema: .agents/skills/testing-taxonomy-review/review-output.schema.json
---

# Testing Taxonomy Review

Distilled from [`docs/guides/testing_taxonomy/`](../../../docs/guides/testing_taxonomy/README.md)
into a reviewable rule catalogue. The long-form vignettes stay the source of truth
(each rule's `doc` links to its vignette); this skill is the **index + decision
framework** an agent applies when reviewing dbt models.

Two artefacts back this skill:
- **`rules.json`** — the machine-readable catalogue (single source of truth for the
  29 rule codes + metadata). The review GHA reads it to build its JSON-schema enum.
- **`review-output.schema.json`** — the structured-output contract the review GHA enforces.

## Rule-code scheme

`<ROLE>[-<SUBROLE>]-<NN>` — a 2-letter role prefix, an optional sub-role segment
(only `time` has one today), then a zero-padded number. Roles are the **stable**
axis; the orthogonal overlays (Wang–Strong data-quality dimension, cost class) are
**columns, not part of the code**, because they vary independently and can change
per vignette.

| Prefix | Role | Column behaviour that triggers it |
|--------|------|-----------------------------------|
| `EN-` | entity | Used in a `JOIN ON` (PK / surrogate / FK / compound grain) |
| `DM-` | dimension | Used in a `GROUP BY` (categorical axis) |
| `MS-` | measure | Inside an aggregate (`SUM`/`COUNT`/`AVG`) |
| `TM-SC-` | time · event-time scalar | `WHERE` / arithmetic / window on a timestamp |
| `TM-GR-` | time · time-grain dimension | `GROUP BY DATE_TRUNC` / a date spine |
| `TM-AU-` | time · system-time / audit | `loaded_at` / `valid_from`+`valid_to` |
| `MD-` | model | Cross-column / whole-model concerns |

## The two heuristics (apply these first)

1. **Grain Heuristic** — every model is defined by its grain (the column tuple that
   uniquely identifies a row). Every model MUST have exactly one grain test
   (**MD-01**). *If you cannot name the grain, the model isn't done.*
2. **Role Multiplication Heuristic** — a column plays more than one role across the
   DAG (`order_id` is an entity in `dim_orders`, an FK in `fct_order_items`, a
   GROUP BY axis in `mart_orders_by_customer`). Its test budget is the **union** of
   the role suites for every role it plays. Don't assign one role per column.

## Decision framework — which codes apply

For each **column**, walk its query roles and union the suites:

```
JOIN ON it?            -> entity     -> EN-01..EN-06   (FK? EN-03/04; composite grain? EN-02; hash surrogate? EN-05)
GROUP BY it?           -> dimension  -> DM-01..DM-05   (enum? DM-01; bounded cardinality? DM-02; shared? DM-03)
Inside an aggregate?   -> measure    -> MS-01..MS-05   (money? MS-03; ratio? MS-04; additivity? MS-02)
date/datetime/ts?      -> time
   WHERE/arith/window  ->   scalar   -> TM-SC-01..03
   GROUP BY DATE_TRUNC ->   grain    -> TM-GR-01
   loaded_at / SCD2    ->   audit    -> TM-AU-01..02
```

For the **model as a whole**, always evaluate:
- **MD-01 grain test** — non-negotiable; flag any model lacking it as a `blocker`.
- **MD-02 contract** / **MD-03 versioning** — if the model is published/consumed.
- **MD-04 refactor-parity** — if the PR refactors SQL claiming no output change.
- **MD-05 unit-tests** — if the model has branching logic (CASE/window/dedup).
- **MD-06 row-count-band** / **MD-07 volume-anomaly** — volume guards (band first; Elementary anomaly when a fixed band is too brittle).

### Package preference ladder (which framework to reach for)

`dbt core → dbt-utils → dbt_expectations → elementary → audit_helper` — climb only
when the lower tier can't express the intent. Notes that bind here:
- **`dbt_expectations` is unmaintained (since 2026-05-21).** Reach for it only for
  regex-with-flags, `row_condition` variants, or date-gap detection; prefer the
  maintained alternative otherwise.
- **Anomaly / drift / freshness-anomaly** → **elementary** (the maintained path),
  not `dbt_expectations` distributional tests. *(Elementary models are PROD-only in
  this project — `dbt_project.yml` — so `*-anomaly` rules are prod-scoped.)*
- **Refactor parity** → **audit_helper** (cheap `quick_are_relations_identical` pre-check first).

### Severity guidance (for review verdicts)

- **blocker** — missing grain test (MD-01), missing FK integrity on a real FK (EN-03),
  missing contract on a published model (MD-02), or any integrity gap that risks join
  fanout / silent KPI corruption.
- **warning** — an applicable role-suite test is absent but the gap is contained
  (e.g. a missing `accepted_values` on a low-stakes categorical).
- **info** — nice-to-have (anomaly monitoring not yet warranted) or a noted, deliberate
  `not_applicable`.

## Rule catalogue (29)

Authoritative metadata + vignette links live in [`rules.json`](./rules.json). Summary:

### EN — entity (JOIN keys)
| Code | Rule | Wang–Strong | Cost | Applies when |
|------|------|-------------|------|--------------|
| EN-01 | unique + not_null on single-col grain | Uniqueness+Completeness | cheap | Single-column grain/PK or downstream JOIN key |
| EN-02 | composite grain unique | Uniqueness | scan-bound | Grain spans 2+ columns |
| EN-03 | FK referential integrity (`relationships`) | Consistency | scan-bound | Column is an FK in a JOIN ON |
| EN-04 | soft-delete-scoped FK (`relationships_where`) | Consistency | scan-bound | FK target has soft-deletes |
| EN-05 | surrogate hash-collision guard | Uniqueness | scan-bound | Surrogate is a hash of natural columns |
| EN-06 | type-stable join key (contract `data_type`) | Validity | free | JOIN key could drift in type across models |

### DM — dimension (GROUP BY axes)
| Code | Rule | Wang–Strong | Cost | Applies when |
|------|------|-------------|------|--------------|
| DM-01 | accepted_values enum | Validity | cheap | Low-cardinality categorical (status/type/country) |
| DM-02 | cardinality bound | Validity+Accuracy | cheap | Distinct-count should stay in a known band |
| DM-03 | conformed dimension (shared seed) | Consistency | cheap | Same dimension appears across marts |
| DM-04 | mutual exclusivity of sibling flags | Consistency | cheap | Mutually-exclusive booleans must not co-fire |
| DM-05 | per-dimension anomaly (Elementary) | Accuracy+Timeliness | history-bound | Monitor a category's drift over time (prod) |

### MS — measure (aggregated facts)
| Code | Rule | Wang–Strong | Cost | Applies when |
|------|------|-------------|------|--------------|
| MS-01 | numeric range (`accepted_range`) | Validity | cheap | Numeric measure with known floor/ceiling |
| MS-02 | additivity tag | Consistency | free | Measure mustn't be summed across a forbidden dim |
| MS-03 | currency-pairing (amount + currency_code) | Validity+Accuracy | cheap | Monetary amount that could mix currencies |
| MS-04 | NaN/Inf / divide-by-zero guard | Validity | cheap | Ratio/rate with a zeroable denominator |
| MS-05 | distribution anomaly (Elementary) | Accuracy | history-bound | Monitor a headline measure's drift (prod) |

### TM — time
| Code | Rule | Wang–Strong | Cost | Applies when |
|------|------|-------------|------|--------------|
| TM-SC-01 | event-time bounds (no future/sentinels) | Validity | cheap | Event timestamp in WHERE/arith/window |
| TM-SC-02 | monotonic timestamp pair | Consistency | cheap | Two timestamps with required ordering |
| TM-SC-03 | TIMESTAMP vs DATETIME contract | Validity | free | TZ semantics matter and could drift |
| TM-GR-01 | calendar spine has no gaps | Completeness+Timeliness | cheap | Date-grain dimension / date spine |
| TM-AU-01 | source freshness + model recency | Timeliness | cheap | `loaded_at`/audit ts, or a source to monitor |
| TM-AU-02 | SCD2 quartet | Consistency | scan-bound | Type-2 SCD with valid_from/valid_to |

### MD — model-level
| Code | Rule | Wang–Strong | Cost | Applies when |
|------|------|-------------|------|--------------|
| MD-01 | grain test (the baseline) | Uniqueness | scan-bound | **Always** — every model |
| MD-02 | contract enforced | Validity | free | Published / consumed mart |
| MD-03 | versioning cutover | Consistency | free | Shipping a breaking change |
| MD-04 | refactor parity (audit_helper) | Accuracy | scan-bound | Refactor claiming zero output change |
| MD-05 | unit tests (dbt 1.8) | Accuracy | free | Branching SQL logic |
| MD-06 | row-count band | Accuracy+Completeness | cheap | Row count should sit in a band |
| MD-07 | volume anomaly (Elementary) | Accuracy+Timeliness | history-bound | Volume monitored over time (prod) |

> **Reserved / referenced:** the taxonomy README's reading order references
> `dimension/accepted-values.md` (→ DM-01) and `dimension/cardinality-guard.md`
> (→ DM-02); both now exist on disk and are coded above.

## Reviewing a PR (procedure)

1. Get the added/changed model files (`git diff --name-only <base>...HEAD -- '*/models/**.sql'`).
2. For each model, read its SQL + its `.yml` schema (existing `data_tests:`).
3. Apply the decision framework per column + the model-level MD rules.
4. For each applicable rule, decide `applicable_present` (a matching test exists) vs
   `applicable_missing` (a gap). Assign severity per the guidance above.
5. Emit findings conforming to `review-output.schema.json` (the GHA enforces this).

The CI implementation lives in
[`.github/workflows/testing-taxonomy-review.yml`](../../../.github/workflows/testing-taxonomy-review.yml)
(engine: [`review.py`](./review.py)), which runs this framework via GitHub Models and upserts
four sticky PR-comment variants so the output formats can be compared:

1. **coverage matrix — changed models** — rows = changed models, columns = applicable rule
   codes, cells = ✅ present / ❌ missing / ➖ n/a.
2. **failures — changed models** — narrowed to rules that apply *and* fail somewhere.
3. **coverage matrix — all models** — variant 1 over every model in the project.
4. **failures — all models** — variant 2 over every model.

Each variant carries its own HTML-comment marker (`<!-- ttr:* -->`) so it updates in place.
