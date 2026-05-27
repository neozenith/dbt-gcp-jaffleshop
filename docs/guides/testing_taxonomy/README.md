# Testing Taxonomy

A pattern catalogue for testing dbt models. Organised the way Martin Fowler organised *Refactoring* — every entry is a vignette with a **Smell**, a named **Pattern**, and the **Mechanics** to apply it.

The vocabulary is borrowed from dbt's semantic layer (MetricFlow). Tests are chosen by **what a column does** in queries — joins, group-bys, aggregates, or time arithmetic — not by what its type is in the warehouse.

## Why this exists

dbt projects accumulate tests one model at a time. Without a vocabulary, every engineer reinvents the same decisions: should `country` get `accepted_values`? Does `order_id` need both `unique` and `not_null` if there's already a `primary_key` constraint? Should refactor parity live in a singular test or an analysis?

This taxonomy answers those questions once, with the trade-offs visible.

## How to use it

1. **You are adding tests to a new model.** Start at [§ Decision tree](#decision-tree). For each column, walk the tree and follow the role link to the matching vignettes.
2. **You are reviewing a PR.** Use the [§ Framework matrix](#framework-matrix) to sanity-check whether the chosen package is the right one for the job.
3. **You hit a data-quality incident.** Search the [§ Vignette index](#vignette-index) by symptom — every vignette's `Smell` section is phrased as a production-visible failure.
4. **You are shipping a breaking change.** Read [`model/contracts.md`](./model/contracts.md), [`model/versioning-cutover.md`](./model/versioning-cutover.md), and [`model/refactor-parity.md`](./model/refactor-parity.md) in order.

## The two heuristics

Two ideas underpin everything below. Internalise these and the rest of the catalogue becomes mechanical.

### 1. The Grain Heuristic

> Every dbt model is defined by its **grain** — the tuple of columns whose combination uniquely identifies a row.

The grain is the answer to "what does one row mean?". The grain is almost always `Entity × {Entity | Dimension} × Time`. Examples:

| Model | Grain |
|-------|-------|
| `fct_orders` | `order_id` |
| `fct_order_items` | `order_id, line_number` |
| `fct_daily_active_users` | `user_id, date_day` |
| `fct_inventory_snapshot` | `warehouse_id, product_id, snapshot_date` |

**Rule:** every dbt model has exactly one `dbt_utils.unique_combination_of_columns` test naming its grain. If you cannot name the grain, the model isn't done. See [`model/grain-test.md`](./model/grain-test.md).

### 2. The Role Multiplication Heuristic

> Most columns play **more than one role** across the DAG.

`order_id` is an entity in `dim_orders`, a foreign key in `fct_order_items`, and a `GROUP BY` axis in `mart_orders_by_customer`. The test budget for a column is the **union** of the role-specific suites for every role it plays anywhere downstream.

The taxonomy is a vocabulary for discovering that union, not a way to assign exactly one role per column.

## Decision tree

Walk this tree for each column in a new model.

```mermaid
flowchart TD
    start(["Pick a column"]):::start

    q1{"Used in<br/>JOIN ON?"}:::q
    q2{"Used in<br/>GROUP BY?"}:::q
    q3{"Inside an aggregate<br/>SUM/COUNT/AVG?"}:::q
    q4{"date/datetime/<br/>timestamp?"}:::q
    qFree{"Used at all<br/>downstream?"}:::q

    entity["entity role<br/><a href='./entity/README.md'>see entity/</a>"]:::entity
    dim["dimension role<br/><a href='./dimension/README.md'>see dimension/</a>"]:::dim
    meas["measure role<br/><a href='./measure/README.md'>see measure/</a>"]:::meas

    q4a{"WHERE / arithmetic /<br/>window function?"}:::q
    q4b{"GROUP BY<br/>DATE_TRUNC?"}:::q
    q4c{"loaded_at /<br/>audit timestamp?"}:::q

    tscalar["event-time scalar<br/><a href='./time/event-time-bounds.md'>see time/</a>"]:::time
    tdim["time-grain dimension<br/><a href='./time/calendar-spine.md'>see time/</a>"]:::time
    taudit["system-time / audit<br/><a href='./time/freshness-source-and-model.md'>see time/</a>"]:::time

    payload["payload column<br/>minimal tests"]:::neutral
    model["see also <a href='./model/README.md'>model/</a><br/>(grain, contract, freshness)"]:::neutral

    start --> q1
    q1 -- yes --> entity --> q2
    q1 -- no --> q2
    q2 -- yes --> dim --> q3
    q2 -- no --> q3
    q3 -- yes --> meas --> q4
    q3 -- no --> q4
    q4 -- yes --> q4a
    q4 -- no --> qFree
    q4a -- yes --> tscalar
    q4a -- no --> q4b
    q4b -- yes --> tdim
    q4b -- no --> q4c
    q4c -- yes --> taudit
    q4c -- no --> tscalar
    qFree -- no --> payload
    qFree -- yes --> model

    classDef start   fill:#475569,stroke:#1e293b,color:#fff,stroke-width:2px
    classDef q       fill:#cbd5e1,stroke:#64748b,color:#1e293b,stroke-width:1px
    classDef entity  fill:#2563eb,stroke:#1e293b,color:#fff,stroke-width:2px
    classDef dim     fill:#7c3aed,stroke:#1e293b,color:#fff,stroke-width:2px
    classDef meas    fill:#047857,stroke:#1e293b,color:#fff,stroke-width:2px
    classDef time    fill:#c2410c,stroke:#1e293b,color:#fff,stroke-width:2px
    classDef neutral fill:#f1f5f9,stroke:#94a3b8,color:#334155,stroke-width:1px
```

A column may answer **yes** to more than one question — that's the Role Multiplication Heuristic. Take the union of the recommended suites.

## Vocabulary / glossary

The roles below are MetricFlow's names. Alternative names from the user's original brief, Kimball, MetricFlow, and Data Vault are listed for cross-referencing.

| Canonical (this guide) | Your brief | Kimball | MetricFlow | Data Vault | Anchor |
|------------------------|------------|---------|------------|------------|--------|
| **entity** | Identity | Surrogate key / FK / degenerate dim | `entity` (primary/foreign/natural) | Hub key / Link key | Anchor ID / Tie |
| **dimension** | Dimensional | Dimension attribute / junk dim | `dimension (categorical)` | Satellite attribute | Attribute / Knot |
| **measure** | Measure | Fact (additive/semi-additive/non-additive) | `measure` (sum/count/avg…) | Transactional satellite attribute | Attribute of event-anchor |
| **time** | Temporal | Date dimension + fact event timestamp | `dimension (time)` | `load_date`, `load_end_date` | `ChangedAt` |
| **time (sub: event-time scalar)** | Temporal — scalar | Fact event timestamp | Primary time dimension | n/a | n/a |
| **time (sub: time-grain dimension)** | Temporal — dimensional | Date dimension at chosen grain | Time dimension with `time_granularity` | n/a | n/a |
| **time (sub: system-time / audit)** | — | SCD2 `valid_from` / `valid_to` | Bitemporal load timestamp | `load_date` | `RecordedAt` |

The full Kimball / Inmon / Data Vault / Anchor / MetricFlow / Wang–Strong mapping table lives in the semantic-column research source (see maintainer notes in vignettes).

## Role folders

| Folder | Role | Hue | What it covers |
|--------|------|-----|----------------|
| [`entity/`](./entity/README.md) | entity | Blue | JOIN keys: PKs, surrogate keys, FK integrity, compound grain, type stability, soft-delete scoping, hash-collision guards |
| [`dimension/`](./dimension/README.md) | dimension | Violet | GROUP BY axes: accepted values, cardinality bounds, mutual exclusivity, conformed dimensions, per-dim anomalies |
| [`measure/`](./measure/README.md) | measure | Emerald | Aggregated facts: numeric range, additivity tagging, currency pairing, distribution anomalies, NaN/Inf guards |
| [`time/`](./time/README.md) | time | Orange | Date/datetime columns: event-time bounds, monotonic pairs, freshness, calendar spines, SCD2 quartet, timezone contracts |
| [`model/`](./model/README.md) | model-level | Slate | Cross-column concerns: grain test, contracts, versioning, refactor parity, unit tests, row-count band, volume anomaly |

## Vignette index

### entity/

- [`unique-key.md`](./entity/unique-key.md) — single-column unique + not_null
- [`compound-grain.md`](./entity/compound-grain.md) — `unique_combination_of_columns`
- [`foreign-key-integrity.md`](./entity/foreign-key-integrity.md) — `relationships`
- [`soft-delete-scoped-fk.md`](./entity/soft-delete-scoped-fk.md) — `relationships_where`
- [`type-stable-join.md`](./entity/type-stable-join.md) — contract `data_type` matches across joined relations
- [`surrogate-collision-guard.md`](./entity/surrogate-collision-guard.md) — natural-key uniqueness alongside surrogate uniqueness

### dimension/

- [`accepted-values.md`](./dimension/accepted-values.md) — enum contract on a categorical
- [`cardinality-guard.md`](./dimension/cardinality-guard.md) — `expect_column_unique_value_count_to_be_between`
- [`mutual-exclusivity.md`](./dimension/mutual-exclusivity.md) — sibling boolean flags do not co-fire
- [`conformed-dimension.md`](./dimension/conformed-dimension.md) — shared seed governs values across models
- [`dimension-anomalies.md`](./dimension/dimension-anomalies.md) — Elementary per-dimension count anomalies

### measure/

- [`numeric-range.md`](./measure/numeric-range.md) — `accepted_range` / `expect_column_values_to_be_between`
- [`additivity-tag.md`](./measure/additivity-tag.md) — additive vs semi-additive vs non-additive (semantic-layer contract)
- [`currency-pairing.md`](./measure/currency-pairing.md) — amount columns always travel with `currency_code`
- [`distribution-anomaly.md`](./measure/distribution-anomaly.md) — mean/stdev anomaly detection
- [`nan-inf-guard.md`](./measure/nan-inf-guard.md) — divide-by-zero / Inf / NaN traps

### time/

- [`event-time-bounds.md`](./time/event-time-bounds.md) — no future, no `1900-01-01` / `9999-12-31` sentinels
- [`monotonic-pair.md`](./time/monotonic-pair.md) — `shipped_at >= ordered_at`, `updated_at >= created_at`
- [`freshness-source-and-model.md`](./time/freshness-source-and-model.md) — source freshness + model recency
- [`calendar-spine.md`](./time/calendar-spine.md) — `sequential_values` on `date_day`
- [`scd2-quartet.md`](./time/scd2-quartet.md) — the four tests every Type-2 dim needs together
- [`timezone-contract.md`](./time/timezone-contract.md) — TIMESTAMP vs DATETIME contract on BigQuery

### model/

- [`grain-test.md`](./model/grain-test.md) — the one test every model must have
- [`contracts.md`](./model/contracts.md) — `contract.enforced: true` (shape, not content)
- [`versioning-cutover.md`](./model/versioning-cutover.md) — ship `v=N+1` without breaking consumers
- [`refactor-parity.md`](./model/refactor-parity.md) — `audit_helper.compare_and_classify_relation_rows`
- [`unit-tests.md`](./model/unit-tests.md) — dbt 1.8 unit tests for branching SQL logic
- [`row-count-band.md`](./model/row-count-band.md) — `expect_table_row_count_to_be_between`
- [`volume-anomaly.md`](./model/volume-anomaly.md) — Elementary volume anomaly detection

## Framework matrix

When multiple packages can express the same intent, this matrix picks the canonical answer for this project. The order of preference is: **dbt core → dbt-utils → dbt_expectations → elementary → audit_helper**, climbing only when each lower tier cannot express what's needed.

| Concern | Reach for first | Escalate when |
|---------|-----------------|---------------|
| Single-column uniqueness | dbt core `unique` | Need to scope by `where:` → still core (config) |
| Composite-key uniqueness | `dbt_utils.unique_combination_of_columns` | Need `row_condition` → `dbt_expectations.expect_compound_columns_to_be_unique` |
| Single-column NOT NULL | dbt core `not_null` | Need conditional (`only when status='closed'`) → core with `where:` config |
| Enum membership | dbt core `accepted_values` | Mixed types or `row_condition` → `dbt_expectations.expect_column_values_to_be_in_set` |
| Numeric range | `dbt_utils.accepted_range` | Need `group_by` per partition → `dbt_expectations.expect_column_values_to_be_between` |
| Referential integrity | dbt core `relationships` | Soft-deletes / scoped → `dbt_utils.relationships_where` |
| Row count parity | `dbt_utils.equal_rowcount` | Tolerance % or grouped → `dbt_expectations.expect_table_row_count_to_equal_other_table` |
| Cross-column expression | `dbt_utils.expression_is_true` | Need group_by → `dbt_expectations` variant |
| Regex on string | `dbt_expectations.expect_column_values_to_match_regex` | (no maintained alternative) |
| Date gap detection | `dbt_utils.sequential_values` | Need explicit start/end dates → `dbt_expectations.expect_row_values_to_have_data_for_every_n_datepart` |
| Anomaly / drift detection | **`elementary`** (anomaly tests) | (don't escalate to dbt_expectations distributional tests — Elementary is the maintained path) |
| Freshness | source `freshness:` block | Model-level → `dbt_utils.recency` or `elementary.freshness_anomalies` |
| Refactor parity | `audit_helper.compare_and_classify_relation_rows` | (cheap pre-check first: `quick_are_relations_identical` on BQ/Snowflake) |
| Schema drift | dbt core `contract` (parse-time) | Source you don't own → `elementary.schema_changes` |
| Type guarantee | dbt core `contract` `data_type` | (DDL-level on table; preflight-only on view) |
| Branching SQL logic correctness | dbt 1.8 unit tests | (not a data test — different machinery) |
| Schema versioning | dbt core `versions` | (paired with `contract.enforced: true`) |

> **Maintenance flag (2026-05):** `dbt_expectations` was marked *"no longer actively supported"* on 2026-05-21. It is still installable and broadly used, but for any test where a maintained alternative exists, prefer that alternative. The only places this guide reaches for `dbt_expectations` are: regex-with-flags, `row_condition` versions of native tests, and gap-detection on a date column — none have first-class replacements.

## Cost classes

Vignettes mark their cost class. Use this to sequence what runs in CI vs. nightly vs. on-demand.

| Class | Meaning | Examples |
|-------|---------|----------|
| **free** | Compile-time only; no warehouse scan | dbt contracts, model versioning declarations |
| **cheap** | O(rows in detection window); usually under a partition | `unique` with `where: created_at >= …` |
| **scan-bound** | Full-table scan per run | unscoped `unique`, `equality` |
| **history-bound** | Reads/writes a metrics history table; first run is expensive, subsequent runs cheap | Elementary anomaly tests, `dbt_expectations` distributional tests |

## Wang–Strong overlay

The orthogonal axis. Every vignette tags the **data-quality dimension** it defends so reviewers can spot coverage gaps.

| Dimension | What it asserts | Typical vignettes |
|-----------|-----------------|-------------------|
| **Uniqueness** | No duplicate rows / keys | `unique-key`, `compound-grain`, `surrogate-collision-guard` |
| **Completeness** | No missing values where required | `unique-key` (not_null half), `dimension/accepted-values` (no nulls if forbidden) |
| **Validity** | Values are in the allowed domain | `accepted-values`, `numeric-range`, `event-time-bounds`, `timezone-contract` |
| **Consistency** | Cross-column / cross-table invariants hold | `monotonic-pair`, `mutual-exclusivity`, `conformed-dimension`, `scd2-quartet` |
| **Accuracy** | Values match the real-world state | `currency-pairing`, `refactor-parity`, `volume-anomaly` |
| **Timeliness** | Data is current enough | `freshness-source-and-model`, `calendar-spine`, `volume-anomaly` |

## Color palette

Every Mermaid diagram in this taxonomy uses these `classDef` blocks. The palette passes **WCAG 2.1 AA for text contrast** on both light and dark GitHub themes (white text on shade-600/700 fills, dark text on shade-100 fills). See [Validation status](#validation-status) below for the full picture.

```text
%% entity role — Blue
classDef entityPrimary   fill:#2563eb,stroke:#1e293b,color:#fff,stroke-width:2px
classDef entitySecondary fill:#93c5fd,stroke:#3b82f6,color:#1e293b,stroke-width:1px
classDef sgEntity        fill:#dbeafe,stroke:#3b82f6,color:#1e293b

%% dimension role — Violet
classDef dimPrimary      fill:#7c3aed,stroke:#1e293b,color:#fff,stroke-width:2px
classDef dimSecondary    fill:#c4b5fd,stroke:#8b5cf6,color:#1e293b,stroke-width:1px
classDef sgDim           fill:#ede9fe,stroke:#8b5cf6,color:#1e293b

%% measure role — Emerald
classDef measurePrimary  fill:#047857,stroke:#1e293b,color:#fff,stroke-width:2px
classDef measureSecondary fill:#6ee7b7,stroke:#10b981,color:#1e293b,stroke-width:1px
classDef sgMeasure       fill:#d1fae5,stroke:#10b981,color:#1e293b

%% time role — Orange
classDef timePrimary     fill:#c2410c,stroke:#1e293b,color:#fff,stroke-width:2px
classDef timeSecondary   fill:#fdba74,stroke:#f97316,color:#1e293b,stroke-width:1px
classDef sgTime          fill:#fff7ed,stroke:#f97316,color:#1e293b

%% model-level — Slate
classDef modelPrimary    fill:#475569,stroke:#1e293b,color:#fff,stroke-width:2px
classDef modelSecondary  fill:#cbd5e1,stroke:#64748b,color:#1e293b,stroke-width:1px
classDef sgModel         fill:#f1f5f9,stroke:#94a3b8,color:#334155

%% Accent: error / fail
classDef fail            fill:#dc2626,stroke:#1e293b,color:#fff,stroke-width:2px

%% Accent: pass / ok
classDef ok              fill:#047857,stroke:#1e293b,color:#fff,stroke-width:2px

%% Accent: decision gate / test (used in every diagram)
classDef gate            fill:#c2410c,stroke:#1e293b,color:#fff,stroke-width:2px
```

### Validation status

Validated with `scripts/mermaid_contrast.ts` from the canonical `mermaidjs_diagrams` skill across all 36 vignettes:

- **Text contrast: 100% AA pass.** Every primary classDef hits ≥5.17:1 (white on shade-600/700 fills) and every secondary classDef hits ≥9.45:1 (slate-800 text on shade-100/300 fills).
- **Border-vs-fill contrast: ~25% pass.** Most primary classDefs fall short of the 3:1 WCAG 1.4.11 rule because Mermaid's dark-fill / white-text idiom can't reach 3:1 border contrast with any conventional stroke choice — pure black borders only reach 2.77:1 against slate-600. The upstream `color_theming.md` reference itself doesn't satisfy this rule. Accepted as advisory: text readability is the load-bearing axis; border visibility is a known constraint of the medium.

The earlier draft used same-hue darker strokes (`stroke:#1e40af` for blue, etc.) which failed *both* text and border AA on emerald and orange. The current palette switches to `stroke:#1e293b` universally and darkens emerald/orange fills to shade-700 — fixing the text-AA failures while accepting the border-AA limitation.

## Conventions

- **Folder naming uses singular nouns** (`entity/`, not `entities/`). A folder name is the role; the file inside is the pattern.
- **File naming uses imperative verbs / nouns of the pattern** (`unique-key.md`, `refactor-parity.md`).
- **Mermaid diagrams render natively on GitHub** — see [`templates/default.md`](./templates/default.md) for the standard layout.
- **SQL examples target BigQuery** (the project's adapter). Where dialect matters (TIMESTAMP vs DATETIME, `regexp_instr` flags, partition pruning), the vignette calls it out.
- **YAML examples assume dbt 1.8+** — they use the `data_tests:` key (not `tests:`) and the `data-tests/` directory (not `tests/`).

## Reading order

If reading the catalogue front-to-back, this is the recommended order:

1. [`model/grain-test.md`](./model/grain-test.md) — the most important test in the entire project
2. [`entity/unique-key.md`](./entity/unique-key.md) → [`entity/compound-grain.md`](./entity/compound-grain.md) → [`entity/foreign-key-integrity.md`](./entity/foreign-key-integrity.md)
3. [`dimension/accepted-values.md`](./dimension/accepted-values.md) → [`dimension/cardinality-guard.md`](./dimension/cardinality-guard.md)
4. [`measure/numeric-range.md`](./measure/numeric-range.md) → [`measure/additivity-tag.md`](./measure/additivity-tag.md)
5. [`time/event-time-bounds.md`](./time/event-time-bounds.md) → [`time/monotonic-pair.md`](./time/monotonic-pair.md)
6. [`model/contracts.md`](./model/contracts.md) → [`model/versioning-cutover.md`](./model/versioning-cutover.md) → [`model/refactor-parity.md`](./model/refactor-parity.md)
7. Anomaly-detection vignettes when the project graduates to needing Elementary

## Template

See [`templates/default.md`](./templates/default.md) for the structure every vignette follows.
