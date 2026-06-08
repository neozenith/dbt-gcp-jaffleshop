# Testing-taxonomy review — per-model, with full lineage

> **Generated** by `adaf report` — deterministic verdicts come from running `adaf.taxonomy.DETECTORS` over the manifest + `catalog.json` (warehouse-resolved columns). No deterministic value is hand-authored. Re-generate: `uv run --directory dbt-jaffleshop adaf report --all --catalog target/catalog.json --review review.json -o <file>`.

- Generated (UTC): 2026-06-08T14:00:09Z
- Catalogue version: `2.0.0` (33 rules) · scope: all models
- Deterministic detectors: `MD-01`, `TM-AU-01`, `MD-02`, `EN-01`, `EN-03`, `TM-SC-03`
- Warehouse-resolved columns available: **True**
- LLM review reconciled: **yes** — 5 call(s), 27376 tokens (from `adaf review --json`)

**How to read it:** *Deterministic* is the yardstick (a detector + a fact). *LLM* is what `adaf review` claimed. *Assessment* flags 🔴 verifiable LLM errors, 🟠 applicability disagreements, 🟡 suppressed-but-flagged, ⚪ unverified (no detector). Start with the worklist, then drill into the model.

<details><summary><b>Detector caveats — read before trusting a 🔴/🟠</b></summary>

The detectors are deterministic but heuristic about *which column plays which role*. Knowing the heuristic tells you whether a flag is a true LLM error or a detector limit:

- **MD-01** counts a model-level `unique` **or** `dbt_utils.unique_combination_of_columns` as a grain test. So a 🔴 *false positive* here means *a uniqueness test exists* — if the LLM wanted an explicit `unique_combination_of_columns`, that is a stricter-style preference, not a hallucinated fact.
- **EN-01** infers the PK as `<model>_id` (singularised) or the **sole** `*_id`/`*_uuid` column. A model with several key columns yields *no identifiable PK* → EN-01 shows **n/a** (a detector limit, surfaced as 🟠 if the LLM asserts it — not an LLM error).
- **EN-03** treats every non-PK `*_id`/`*_uuid` column as a FK needing a `relationships` test; when the PK isn't identified it may over-include a key as a FK.
- **TM-SC-03** needs `catalog.json` (a build) to see column types; without it, it reports n/a.
- Columns are **warehouse-resolved** from `catalog.json` when present (authoritative), else YAML-declared.

</details>

## False-positive / false-negative worklist

Every place the LLM `adaf review` disagrees with the deterministic ground truth. 🔴 = a verifiable LLM error (a detector proves it wrong); 🟠 = an applicability disagreement to adjudicate; 🟡 = the project suppressed it but the LLM still raised it. Agreements are omitted here (they appear per-model below).

| Model | Rule | Deterministic | LLM | Assessment | Evidence (fact) |
|---|---|---|---|---|---|
| `orders` | `EN-03` | ❌ warning | present | 🔴 **LLM FALSE NEGATIVE** — missed a real gap (claimed covered) | FK column(s) without a relationships test: location_id |
| `products` | `EN-01` | ❌ warning | present | 🔴 **LLM FALSE NEGATIVE** — missed a real gap (claimed covered) | PK 'product_id' is missing unique, not_null |
| `stg_customers` | `MD-01` | ✅ pass | gap | 🔴 **LLM FALSE POSITIVE** — flagged a gap, but the test exists | has a uniqueness/grain test |
| `stg_locations` | `MD-01` | ✅ pass | gap | 🔴 **LLM FALSE POSITIVE** — flagged a gap, but the test exists | has a uniqueness/grain test |
| `stg_order_items` | `MD-01` | ✅ pass | gap | 🔴 **LLM FALSE POSITIVE** — flagged a gap, but the test exists | has a uniqueness/grain test |
| `stg_orders` | `MD-01` | ✅ pass | gap | 🔴 **LLM FALSE POSITIVE** — flagged a gap, but the test exists | has a uniqueness/grain test |
| `stg_products` | `MD-01` | ✅ pass | gap | 🔴 **LLM FALSE POSITIVE** — flagged a gap, but the test exists | has a uniqueness/grain test |
| `stg_order_items` | `EN-01` | — n/a | present | 🟠 applicability — LLM says present; deterministic finds the rule n/a here | detector matched no role/precondition on this node |
| `stg_orders` | `EN-01` | — n/a | present | 🟠 applicability — LLM says present; deterministic finds the rule n/a here | detector matched no role/precondition on this node |
| `stg_supplies` | `EN-01` | — n/a | present | 🟠 applicability — LLM says present; deterministic finds the rule n/a here | detector matched no role/precondition on this node |
| `supplies` | `EN-01` | — n/a | present | 🟠 applicability — LLM says present; deterministic finds the rule n/a here | detector matched no role/precondition on this node |

## Models

### `customers` — model (layer `marts`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (9 warehouse-resolved from `catalog.json`): `customer_id`:STRING, `customer_name`:STRING, `count_lifetime_orders`:INT64, `first_ordered_at`:TIMESTAMP, `last_ordered_at`:TIMESTAMP, `lifetime_spend_pretax`:NUMERIC, `lifetime_tax_paid`:NUMERIC, `lifetime_spend`:NUMERIC, `customer_type`:STRING
- Tests present: `accepted_values(customer_type)`, `dbt_utils.expression_is_true`, `not_null(customer_id)`, `unique(customer_id)`
- Contract enforced: `False`
- Inferred PK: `customer_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: none
- TZ-sensitive (TIMESTAMP/DATETIME) columns: `first_ordered_at`, `last_ordered_at`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | ❌ warning | mart has no enforced contract — add contract: {enforced: true} to pin its shape | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | customer_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | ✅ yes | applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._ | ❌ warning | tz-sensitive column(s) first_ordered_at, last_ordered_at have no type contract — pin TIMESTAMP vs DATETIME with contract.enforced + data_type | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `DM-01` | Validity | _(no detector)_ | present | ⚪ unverified — no deterministic detector; LLM judgement only |
| `MS-01` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `TM-SC-01` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-01` | Uniqueness/Completeness | ✅ pass — customer_id has unique + not_null | present | ✅ agree (present) |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-01` | Uniqueness | ✅ pass — has a uniqueness/grain test | present | ✅ agree (present) |
| `MD-02` | Validity | ❌ warning — mart has no enforced contract — add contract: {enforced: true} to pin its shape | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | ❌ warning — tz-sensitive column(s) first_ordered_at, last_ordered_at have no type contract — pin TIMESTAMP vs DATETIME with contract.enforced + data_type | _(not emitted)_ | · |

### `locations` — model (layer `marts`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (4 warehouse-resolved from `catalog.json`): `location_id`:STRING, `location_name`:STRING, `tax_rate`:FLOAT64, `opened_date`:TIMESTAMP  ⚠️ (0 declared in YAML — a documentation gap; these are warehouse-resolved)
- Tests present: none
- Contract enforced: `False`
- Inferred PK: `location_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: none
- TZ-sensitive (TIMESTAMP/DATETIME) columns: `opened_date`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ❌ blocker | no grain test — add unique_combination_of_columns (or unique) naming the grain | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | ❌ warning | mart has no enforced contract — add contract: {enforced: true} to pin its shape | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ❌ warning | PK 'location_id' is missing unique, not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | ✅ yes | applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._ | ❌ warning | tz-sensitive column(s) opened_date have no type contract — pin TIMESTAMP vs DATETIME with contract.enforced + data_type | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `TM-GR-01` | Completeness/Timeliness | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-01` | Uniqueness/Completeness | ❌ warning — PK 'location_id' is missing unique, not_null | gap | ✅ agree (gap) |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-01` | Uniqueness | ❌ blocker — no grain test — add unique_combination_of_columns (or unique) naming the grain | gap | ✅ agree (gap) |
| `MD-02` | Validity | ❌ warning — mart has no enforced contract — add contract: {enforced: true} to pin its shape | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | ❌ warning — tz-sensitive column(s) opened_date have no type contract — pin TIMESTAMP vs DATETIME with contract.enforced + data_type | _(not emitted)_ | · |

### `metricflow_time_spine` — model (layer `marts`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (1 warehouse-resolved from `catalog.json`): `date_day`:DATE  ⚠️ (0 declared in YAML — a documentation gap; these are warehouse-resolved)
- Tests present: none
- Contract enforced: `False`
- Inferred PK: (none identifiable)
- Key (`*_id`/`*_uuid`) columns beyond the PK: none

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | 🟡 suppressed | no grain test — add unique_combination_of_columns (or unique) naming the grain — **suppressed**: Generated MetricFlow time spine — a synthetic date dimension with no natural grain key to test and no consumer contract to enforce. | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | 🟡 suppressed | mart has no enforced contract — add contract: {enforced: true} to pin its shape — **suppressed**: Generated MetricFlow time spine — a synthetic date dimension with no natural grain key to test and no consumer contract to enforce. | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `TM-GR-01` | Completeness/Timeliness | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-01` | Uniqueness/Completeness | — n/a | _(not emitted)_ | · |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-01` | Uniqueness | 🟡 suppressed | n/a | ✅ suppressed / LLM n/a |
| `MD-02` | Validity | 🟡 suppressed | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

### `order_items` — model (layer `marts`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (9 warehouse-resolved from `catalog.json`): `order_item_id`:STRING, `order_id`:STRING, `product_id`:STRING, `ordered_at`:TIMESTAMP, `product_name`:STRING, `product_price`:NUMERIC, `is_food_item`:BOOL, `is_drink_item`:BOOL, `supply_cost`:NUMERIC
- Tests present: `not_null(order_item_id)`, `relationships(order_id)`, `unique(order_item_id)`
- Contract enforced: `False`
- Inferred PK: `order_item_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: `order_id`, `product_id`
- TZ-sensitive (TIMESTAMP/DATETIME) columns: `ordered_at`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | ❌ warning | mart has no enforced contract — add contract: {enforced: true} to pin its shape | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | order_item_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | ✅ yes | applies_when: _Column is a foreign key used in a JOIN ON to another model._ | ❌ warning | FK column(s) without a relationships test: product_id | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | ✅ yes | applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._ | ❌ warning | tz-sensitive column(s) ordered_at have no type contract — pin TIMESTAMP vs DATETIME with contract.enforced + data_type | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `DM-01` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-04` | Consistency | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `MS-01` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `MS-03` | Validity/Accuracy | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `TM-GR-01` | Completeness/Timeliness | _(no detector)_ | present | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-01` | Uniqueness/Completeness | ✅ pass — order_item_id has unique + not_null | present | ✅ agree (present) |
| `EN-03` | Consistency | ❌ warning — FK column(s) without a relationships test: product_id | gap | ✅ agree (gap) |
| `MD-01` | Uniqueness | ✅ pass — has a uniqueness/grain test | present | ✅ agree (present) |
| `MD-02` | Validity | ❌ warning — mart has no enforced contract — add contract: {enforced: true} to pin its shape | gap | ✅ agree (gap) |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | ❌ warning — tz-sensitive column(s) ordered_at have no type contract — pin TIMESTAMP vs DATETIME with contract.enforced + data_type | gap | ✅ agree (gap) |

### `orders` — model (layer `marts`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (18 warehouse-resolved from `catalog.json`): `order_id`:STRING, `location_id`:STRING, `customer_id`:STRING, `subtotal_cents`:INT64, `tax_paid_cents`:INT64, `order_total_cents`:INT64, `subtotal`:NUMERIC, `tax_paid`:NUMERIC, `order_total`:NUMERIC, `ordered_at`:TIMESTAMP, `order_cost`:NUMERIC, `order_items_subtotal`:NUMERIC, `count_food_items`:INT64, `count_drink_items`:INT64, `count_order_items`:INT64, `is_food_order`:BOOL, `is_drink_order`:BOOL, `customer_order_number`:INT64
- Tests present: `dbt_utils.expression_is_true`, `not_null(order_id)`, `relationships(customer_id)`, `relationships(order_id)`, `unique(order_id)`
- Contract enforced: `False`
- Inferred PK: `order_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: `location_id`, `customer_id`
- TZ-sensitive (TIMESTAMP/DATETIME) columns: `ordered_at`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | ❌ warning | mart has no enforced contract — add contract: {enforced: true} to pin its shape | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | order_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | ✅ yes | applies_when: _Column is a foreign key used in a JOIN ON to another model._ | ❌ warning | FK column(s) without a relationships test: location_id | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | ✅ yes | applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._ | ❌ warning | tz-sensitive column(s) ordered_at have no type contract — pin TIMESTAMP vs DATETIME with contract.enforced + data_type | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `EN-03` | Consistency | ❌ warning — FK column(s) without a relationships test: location_id | present | 🔴 **LLM FALSE NEGATIVE** — missed a real gap (claimed covered) |
| `DM-04` | Consistency | _(no detector)_ | present | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-04` | Consistency | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `MD-06` | Accuracy/Completeness | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `MS-01` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `TM-GR-01` | Completeness/Timeliness | _(no detector)_ | present | ⚪ unverified — no deterministic detector; LLM judgement only |
| `TM-SC-01` | Validity | _(no detector)_ | present | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-01` | Uniqueness/Completeness | ✅ pass — order_id has unique + not_null | present | ✅ agree (present) |
| `MD-01` | Uniqueness | ✅ pass — has a uniqueness/grain test | present | ✅ agree (present) |
| `MD-02` | Validity | ❌ warning — mart has no enforced contract — add contract: {enforced: true} to pin its shape | gap | ✅ agree (gap) |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | ❌ warning — tz-sensitive column(s) ordered_at have no type contract — pin TIMESTAMP vs DATETIME with contract.enforced + data_type | gap | ✅ agree (gap) |

### `products` — model (layer `marts`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (7 warehouse-resolved from `catalog.json`): `product_id`:STRING, `product_name`:STRING, `product_type`:STRING, `product_description`:STRING, `product_price`:NUMERIC, `is_food_item`:BOOL, `is_drink_item`:BOOL  ⚠️ (0 declared in YAML — a documentation gap; these are warehouse-resolved)
- Tests present: none
- Contract enforced: `False`
- Inferred PK: `product_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: none

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ❌ blocker | no grain test — add unique_combination_of_columns (or unique) naming the grain | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | ❌ warning | mart has no enforced contract — add contract: {enforced: true} to pin its shape | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ❌ warning | PK 'product_id' is missing unique, not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `EN-01` | Uniqueness/Completeness | ❌ warning — PK 'product_id' is missing unique, not_null | present | 🔴 **LLM FALSE NEGATIVE** — missed a real gap (claimed covered) |
| `DM-01` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `DM-02` | Validity/Accuracy | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `DM-04` | Consistency | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-06` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-01` | Uniqueness | ❌ blocker — no grain test — add unique_combination_of_columns (or unique) naming the grain | gap | ✅ agree (gap) |
| `MD-02` | Validity | ❌ warning — mart has no enforced contract — add contract: {enforced: true} to pin its shape | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

### `supplies` — model (layer `marts`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (6 warehouse-resolved from `catalog.json`): `supply_uuid`:STRING, `supply_id`:STRING, `product_id`:STRING, `supply_name`:STRING, `supply_cost`:NUMERIC, `is_perishable_supply`:BOOL  ⚠️ (0 declared in YAML — a documentation gap; these are warehouse-resolved)
- Tests present: none
- Contract enforced: `False`
- Inferred PK: (none identifiable)
- Key (`*_id`/`*_uuid`) columns beyond the PK: `supply_uuid`, `supply_id`, `product_id`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ❌ blocker | no grain test — add unique_combination_of_columns (or unique) naming the grain | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | ❌ warning | mart has no enforced contract — add contract: {enforced: true} to pin its shape | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | ✅ yes | applies_when: _Column is a foreign key used in a JOIN ON to another model._ | ❌ warning | FK column(s) without a relationships test: supply_uuid, supply_id, product_id | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `EN-01` | Uniqueness/Completeness | — n/a | present | 🟠 applicability — LLM says present; deterministic finds the rule n/a here |
| `DM-04` | Consistency | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-06` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-03` | Consistency | ❌ warning — FK column(s) without a relationships test: supply_uuid, supply_id, product_id | gap | ✅ agree (gap) |
| `MD-01` | Uniqueness | ❌ blocker — no grain test — add unique_combination_of_columns (or unique) naming the grain | gap | ✅ agree (gap) |
| `MD-02` | Validity | ❌ warning — mart has no enforced contract — add contract: {enforced: true} to pin its shape | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

### `stg_customers` — model (layer `staging`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (2 warehouse-resolved from `catalog.json`): `customer_id`:STRING, `customer_name`:STRING
- Tests present: `not_null(customer_id)`, `relationships(customer_id)`, `unique(customer_id)`
- Contract enforced: `False`
- Inferred PK: `customer_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: none

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | customer_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ pass — has a uniqueness/grain test | gap | 🔴 **LLM FALSE POSITIVE** — flagged a gap, but the test exists |
| `EN-06` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-01` | Uniqueness/Completeness | ✅ pass — customer_id has unique + not_null | present | ✅ agree (present) |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-02` | Validity | — n/a | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

### `stg_locations` — model (layer `staging`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (4 warehouse-resolved from `catalog.json`): `location_id`:STRING, `location_name`:STRING, `tax_rate`:FLOAT64, `opened_date`:TIMESTAMP
- Tests present: `not_null(location_id)`, `unique(location_id)`
- Contract enforced: `False`
- Inferred PK: `location_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: none
- TZ-sensitive (TIMESTAMP/DATETIME) columns: `opened_date`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | location_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | ✅ yes | applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._ | ❌ warning | tz-sensitive column(s) opened_date have no type contract — pin TIMESTAMP vs DATETIME with contract.enforced + data_type | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ pass — has a uniqueness/grain test | gap | 🔴 **LLM FALSE POSITIVE** — flagged a gap, but the test exists |
| `EN-06` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `TM-GR-01` | Completeness/Timeliness | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-01` | Uniqueness/Completeness | ✅ pass — location_id has unique + not_null | present | ✅ agree (present) |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-02` | Validity | — n/a | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | ❌ warning — tz-sensitive column(s) opened_date have no type contract — pin TIMESTAMP vs DATETIME with contract.enforced + data_type | _(not emitted)_ | · |

### `stg_order_items` — model (layer `staging`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (3 warehouse-resolved from `catalog.json`): `order_item_id`:STRING, `order_id`:STRING, `product_id`:STRING
- Tests present: `not_null(order_id)`, `not_null(order_item_id)`, `relationships(order_id)`, `unique(order_item_id)`
- Contract enforced: `False`
- Inferred PK: (none identifiable)
- Key (`*_id`/`*_uuid`) columns beyond the PK: `order_item_id`, `order_id`, `product_id`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | ✅ yes | applies_when: _Column is a foreign key used in a JOIN ON to another model._ | ❌ warning | FK column(s) without a relationships test: order_item_id, product_id | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ pass — has a uniqueness/grain test | gap | 🔴 **LLM FALSE POSITIVE** — flagged a gap, but the test exists |
| `EN-01` | Uniqueness/Completeness | — n/a | present | 🟠 applicability — LLM says present; deterministic finds the rule n/a here |
| `EN-06` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-03` | Consistency | ❌ warning — FK column(s) without a relationships test: order_item_id, product_id | gap | ✅ agree (gap) |
| `MD-02` | Validity | — n/a | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

### `stg_orders` — model (layer `staging`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (10 warehouse-resolved from `catalog.json`): `order_id`:STRING, `location_id`:STRING, `customer_id`:STRING, `subtotal_cents`:INT64, `tax_paid_cents`:INT64, `order_total_cents`:INT64, `subtotal`:NUMERIC, `tax_paid`:NUMERIC, `order_total`:NUMERIC, `ordered_at`:TIMESTAMP
- Tests present: `dbt_utils.expression_is_true`, `not_null(order_id)`, `relationships(order_id)`, `unique(order_id)`
- Contract enforced: `False`
- Inferred PK: (none identifiable)
- Key (`*_id`/`*_uuid`) columns beyond the PK: `order_id`, `location_id`, `customer_id`
- TZ-sensitive (TIMESTAMP/DATETIME) columns: `ordered_at`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | ✅ yes | applies_when: _Column is a foreign key used in a JOIN ON to another model._ | ❌ warning | FK column(s) without a relationships test: location_id, customer_id | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | ✅ yes | applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._ | ❌ warning | tz-sensitive column(s) ordered_at have no type contract — pin TIMESTAMP vs DATETIME with contract.enforced + data_type | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ pass — has a uniqueness/grain test | gap | 🔴 **LLM FALSE POSITIVE** — flagged a gap, but the test exists |
| `EN-01` | Uniqueness/Completeness | — n/a | present | 🟠 applicability — LLM says present; deterministic finds the rule n/a here |
| `EN-06` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `TM-GR-01` | Completeness/Timeliness | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-03` | Consistency | ❌ warning — FK column(s) without a relationships test: location_id, customer_id | _(not emitted)_ | · |
| `MD-02` | Validity | — n/a | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | ❌ warning — tz-sensitive column(s) ordered_at have no type contract — pin TIMESTAMP vs DATETIME with contract.enforced + data_type | _(not emitted)_ | · |

### `stg_products` — model (layer `staging`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (7 warehouse-resolved from `catalog.json`): `product_id`:STRING, `product_name`:STRING, `product_type`:STRING, `product_description`:STRING, `product_price`:NUMERIC, `is_food_item`:BOOL, `is_drink_item`:BOOL
- Tests present: `not_null(product_id)`, `unique(product_id)`
- Contract enforced: `False`
- Inferred PK: `product_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: none

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | product_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ pass — has a uniqueness/grain test | gap | 🔴 **LLM FALSE POSITIVE** — flagged a gap, but the test exists |
| `DM-04` | Consistency | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-06` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `MS-01` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-01` | Uniqueness/Completeness | ✅ pass — product_id has unique + not_null | present | ✅ agree (present) |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-02` | Validity | — n/a | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

### `stg_supplies` — model (layer `staging`)

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (6 warehouse-resolved from `catalog.json`): `supply_uuid`:STRING, `supply_id`:STRING, `product_id`:STRING, `supply_name`:STRING, `supply_cost`:NUMERIC, `is_perishable_supply`:BOOL
- Tests present: `not_null(supply_uuid)`, `unique(supply_uuid)`
- Contract enforced: `False`
- Inferred PK: (none identifiable)
- Key (`*_id`/`*_uuid`) columns beyond the PK: `supply_uuid`, `supply_id`, `product_id`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | ✅ yes | applies_when: _Column is a foreign key used in a JOIN ON to another model._ | ❌ warning | FK column(s) without a relationships test: supply_uuid, supply_id, product_id | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `EN-01` | Uniqueness/Completeness | — n/a | present | 🟠 applicability — LLM says present; deterministic finds the rule n/a here |
| `MS-01` | Validity | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `MS-03` | Validity/Accuracy | _(no detector)_ | gap | ⚪ unverified — no deterministic detector; LLM judgement only |
| `EN-03` | Consistency | ❌ warning — FK column(s) without a relationships test: supply_uuid, supply_id, product_id | gap | ✅ agree (gap) |
| `MD-01` | Uniqueness | ✅ pass — has a uniqueness/grain test | present | ✅ agree (present) |
| `MD-02` | Validity | — n/a | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | — n/a | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

## Sources

### `raw_customers` — source

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (0 YAML-declared; no catalog): —
- Tests present: none
- Declares a freshness SLA: `False`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | —  no | role/precondition not met (applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | ✅ yes | applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._ | ❌ blocker | source has no freshness: block — add loaded_at_field + warn_after/error_after | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `EN-01` | Uniqueness/Completeness | — n/a | _(not emitted)_ | · |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-01` | Uniqueness | — n/a | _(not emitted)_ | · |
| `MD-02` | Validity | — n/a | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | ❌ blocker — source has no freshness: block — add loaded_at_field + warn_after/error_after | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

### `raw_items` — source

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (0 YAML-declared; no catalog): —
- Tests present: none
- Declares a freshness SLA: `False`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | —  no | role/precondition not met (applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | ✅ yes | applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._ | ❌ blocker | source has no freshness: block — add loaded_at_field + warn_after/error_after | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `EN-01` | Uniqueness/Completeness | — n/a | _(not emitted)_ | · |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-01` | Uniqueness | — n/a | _(not emitted)_ | · |
| `MD-02` | Validity | — n/a | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | ❌ blocker — source has no freshness: block — add loaded_at_field + warn_after/error_after | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

### `raw_orders` — source

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (0 YAML-declared; no catalog): —
- Tests present: none
- Declares a freshness SLA: `False`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | —  no | role/precondition not met (applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | ✅ yes | applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._ | ❌ blocker | source has no freshness: block — add loaded_at_field + warn_after/error_after | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `EN-01` | Uniqueness/Completeness | — n/a | _(not emitted)_ | · |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-01` | Uniqueness | — n/a | _(not emitted)_ | · |
| `MD-02` | Validity | — n/a | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | ❌ blocker — source has no freshness: block — add loaded_at_field + warn_after/error_after | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

### `raw_products` — source

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (0 YAML-declared; no catalog): —
- Tests present: none
- Declares a freshness SLA: `False`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | —  no | role/precondition not met (applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | ✅ yes | applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._ | ❌ blocker | source has no freshness: block — add loaded_at_field + warn_after/error_after | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `EN-01` | Uniqueness/Completeness | — n/a | _(not emitted)_ | · |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-01` | Uniqueness | — n/a | _(not emitted)_ | · |
| `MD-02` | Validity | — n/a | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | ❌ blocker — source has no freshness: block — add loaded_at_field + warn_after/error_after | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

### `raw_stores` — source

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (0 YAML-declared; no catalog): —
- Tests present: none
- Declares a freshness SLA: `False`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | —  no | role/precondition not met (applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | ✅ yes | applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._ | ❌ blocker | source has no freshness: block — add loaded_at_field + warn_after/error_after | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `EN-01` | Uniqueness/Completeness | — n/a | _(not emitted)_ | · |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-01` | Uniqueness | — n/a | _(not emitted)_ | · |
| `MD-02` | Validity | — n/a | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | ❌ blocker — source has no freshness: block — add loaded_at_field + warn_after/error_after | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

### `raw_supplies` — source

**Facts** (the source of every deterministic verdict below — from `manifest.json` + `catalog.json`):

- Columns (0 YAML-declared; no catalog): —
- Tests present: none
- Declares a freshness SLA: `False`

**Deterministic evaluation** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (fact) | Detector (code) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | —  no | role/precondition not met (applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | ✅ yes | applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._ | ❌ blocker | source has no freshness: block — add loaded_at_field + warn_after/error_after | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (applies_when: _Column is a foreign key used in a JOIN ON to another model._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |
| `TM-SC-03` | Validity | —  no | role/precondition not met (applies_when: _A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME._) | — n/a | detector matched no role/precondition on this node | `adaf.taxonomy._detect_tmsc03` — TM-SC-03 timezone-contract (hybrid): a TIMESTAMP/DATETIME column's tz semantics must be pinned. |

**LLM reconciliation** (`adaf review` vs deterministic — your false-positive / false-negative surface):

| Rule | DAMA-UK6 | Deterministic | LLM | Assessment |
|---|---|---|---|---|
| `EN-01` | Uniqueness/Completeness | — n/a | _(not emitted)_ | · |
| `EN-03` | Consistency | — n/a | _(not emitted)_ | · |
| `MD-01` | Uniqueness | — n/a | _(not emitted)_ | · |
| `MD-02` | Validity | — n/a | _(not emitted)_ | · |
| `TM-AU-01` | Timeliness | ❌ blocker — source has no freshness: block — add loaded_at_field + warn_after/error_after | _(not emitted)_ | · |
| `TM-SC-03` | Validity | — n/a | _(not emitted)_ | · |

## Rules with no deterministic detector

These rules' applicability depends on column semantics or intent the manifest/catalog cannot prove (e.g. *is this numeric a ratio?*, *is this PR a refactor?*). The report does **not** assert them deterministically; in the reconciliation above they show as ⚪ *unverified* — the LLM's judgement, for you to confirm. Their catalogue `applies_when` is the reference:

| Rule | DAMA-UK6 | detection | Applies when |
|---|---|---|---|
| `EN-02` | Uniqueness | hybrid | Grain spans 2+ columns (e.g. order_id + line_number). |
| `EN-04` | Consistency | llm | FK target has soft-deletes (deleted_at / is_active) that would false-positive a plain relationships test. |
| `EN-05` | Uniqueness | llm | Surrogate key is a hash (dbt_utils.generate_surrogate_key) of natural columns. |
| `EN-06` | Validity | hybrid | A JOIN key crosses models that could drift in type (e.g. string id vs int id). |
| `DM-01` | Validity | hybrid | Column is a low-cardinality categorical used in GROUP BY / filters (status, type, country). |
| `DM-02` | Validity/Accuracy | llm | A categorical's distinct count should stay within a known band (e.g. ~200 countries). |
| `DM-03` | Consistency | llm | The same dimension (e.g. region, channel) appears in multiple marts and must conform. |
| `DM-04` | Consistency | llm | Model has mutually-exclusive flags (is_new / is_returning) that must sum to <= 1. |
| `DM-05` | Accuracy/Timeliness | llm | A high-value categorical's distribution must be monitored over time; project already runs Elementary. |
| `MS-01` | Validity | hybrid | Column is a numeric measure with a known floor/ceiling (price >= 0, pct 0-100). |
| `MS-02` | Consistency | llm | Column is aggregated (SUM/AVG) and could be wrongly summed across time/entity (e.g. a balance, a ratio). |
| `MS-03` | Validity/Accuracy | hybrid | Model has a monetary amount that could mix currencies if currency_code is missing/null. |
| `MS-04` | Validity | llm | Measure is a ratio/rate computed by division where the denominator can be zero. |
| `MS-05` | Accuracy | llm | A headline measure must be monitored for silent drift over time; project runs Elementary. |
| `TM-SC-01` | Validity | hybrid | Column is an event timestamp used in WHERE / arithmetic / window functions. |
| `TM-SC-02` | Consistency | llm | Model has two timestamps with a required ordering (start/end, created/updated). |
| `TM-GR-01` | Completeness/Timeliness | hybrid | Column is a date-grain dimension built by GROUP BY DATE_TRUNC / a date spine. |
| `TM-AU-02` | Consistency | hybrid | Model is a Type-2 slowly-changing dimension (snapshot with valid_from/valid_to). |
| `TM-AU-03` | Timeliness | llm | A loaded_at / event timestamp whose update cadence is irregular or seasonal, so a fixed source freshness: SLA (TM-AU-01) is too brittle; project runs Elementary (prod). |
| `MD-03` | Consistency | llm | A breaking schema change to a contracted/consumed model is being shipped. |
| `MD-04` | Accuracy | llm | PR refactors a model's SQL with the intent of zero output change. |
| `MD-05` | Accuracy | hybrid | Model has non-trivial branching logic (CASE, window, dedup) whose correctness isn't a data test. |
| `MD-06` | Accuracy/Completeness | llm | Model's row count should sit in a stable band (e.g. a daily mart). |
| `MD-07` | Accuracy/Timeliness | llm | Model's volume must be monitored over time and a fixed band is too brittle; project runs Elementary. |
| `MD-08` | Validity | llm | Model reads an upstream source/table you don't control, so a dbt contract can't catch the drift at parse time; project runs Elementary (prod). |
| `MD-09` | Completeness/Accuracy | llm | A wide model where hand-coding a rule per column is impractical and you want automated drift coverage on column statistics; project runs Elementary (prod). |
| `MD-10` | Validity | llm | Model publishes/consumes a JSON (or stringified-JSON) column whose internal keys/types must hold and can't be pinned by a column data_type contract. |
