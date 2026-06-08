# Testing-taxonomy review — per-model, with full lineage

> **Generated** by `adaf report` — every verdict below is produced by running the detectors in `adaf.taxonomy.DETECTORS` over `target/manifest.json`. No value is hand-authored. Re-generate with `uv run --directory dbt-jaffleshop adaf report --all -o <file>`.

- Generated (UTC): 2026-06-08T13:41:40Z
- Catalogue version: `2.0.0` (33 rules) · scope: all models
- Detectors applied: `MD-01`, `TM-AU-01`, `MD-02`, `EN-01`, `EN-03` (the rules whose applicability + pass/fail are statically decidable)

**How to read a row:** *Applies?* = the detector matched this node's role/structure. *Verdict* = the detector's status (pass / blocker / warning / suppressed). *Evidence* = the exact manifest fact. *Detector* = the function that decided it (and its one-line predicate).

## Models

### `customers` — model (layer `marts`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (9): `customer_id`, `customer_name`, `count_lifetime_orders`, `first_ordered_at`, `last_ordered_at`, `lifetime_spend_pretax`, `lifetime_tax_paid`, `lifetime_spend`, `customer_type`
- Tests present: `accepted_values(customer_type)`, `dbt_utils.expression_is_true`, `not_null(customer_id)`, `unique(customer_id)`
- Contract enforced: `False`
- Inferred PK: `customer_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: none

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | ❌ warning | mart has no enforced contract — add contract: {enforced: true} to pin its shape | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | customer_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `locations` — model (layer `marts`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (0): —
- Tests present: none
- Contract enforced: `False`
- Inferred PK: (none identifiable)
- Key (`*_id`/`*_uuid`) columns beyond the PK: none
- ⚠️ **No columns declared in this model's YAML** — so the key-based rules (EN-*) below report _n/a_ not because the model has no keys, but because none are declared to evaluate. Declaring columns is itself the first gap to close. (Columns here are YAML-declared, from the manifest — not warehouse-resolved.)

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ❌ blocker | no grain test — add unique_combination_of_columns (or unique) naming the grain | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | ❌ warning | mart has no enforced contract — add contract: {enforced: true} to pin its shape | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (rule applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `metricflow_time_spine` — model (layer `marts`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (0): —
- Tests present: none
- Contract enforced: `False`
- Inferred PK: (none identifiable)
- Key (`*_id`/`*_uuid`) columns beyond the PK: none
- ⚠️ **No columns declared in this model's YAML** — so the key-based rules (EN-*) below report _n/a_ not because the model has no keys, but because none are declared to evaluate. Declaring columns is itself the first gap to close. (Columns here are YAML-declared, from the manifest — not warehouse-resolved.)

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | 🟡 suppressed | no grain test — add unique_combination_of_columns (or unique) naming the grain — **suppressed**: Generated MetricFlow time spine — a synthetic date dimension with no natural grain key to test and no consumer contract to enforce. | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | 🟡 suppressed | mart has no enforced contract — add contract: {enforced: true} to pin its shape — **suppressed**: Generated MetricFlow time spine — a synthetic date dimension with no natural grain key to test and no consumer contract to enforce. | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (rule applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `order_items` — model (layer `marts`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (2): `order_item_id`, `order_id`
- Tests present: `not_null(order_item_id)`, `relationships(order_id)`, `unique(order_item_id)`
- Contract enforced: `False`
- Inferred PK: `order_item_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: `order_id`

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | ❌ warning | mart has no enforced contract — add contract: {enforced: true} to pin its shape | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | order_item_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | ✅ yes | applies_when: _Column is a foreign key used in a JOIN ON to another model._ | ✅ pass | all FK column(s) have relationships tests: order_id | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `orders` — model (layer `marts`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (7): `order_id`, `customer_id`, `order_total`, `ordered_at`, `order_cost`, `is_food_order`, `is_drink_order`
- Tests present: `dbt_utils.expression_is_true`, `not_null(order_id)`, `relationships(customer_id)`, `relationships(order_id)`, `unique(order_id)`
- Contract enforced: `False`
- Inferred PK: `order_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: `customer_id`

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | ❌ warning | mart has no enforced contract — add contract: {enforced: true} to pin its shape | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | order_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | ✅ yes | applies_when: _Column is a foreign key used in a JOIN ON to another model._ | ✅ pass | all FK column(s) have relationships tests: customer_id | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `products` — model (layer `marts`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (0): —
- Tests present: none
- Contract enforced: `False`
- Inferred PK: (none identifiable)
- Key (`*_id`/`*_uuid`) columns beyond the PK: none
- ⚠️ **No columns declared in this model's YAML** — so the key-based rules (EN-*) below report _n/a_ not because the model has no keys, but because none are declared to evaluate. Declaring columns is itself the first gap to close. (Columns here are YAML-declared, from the manifest — not warehouse-resolved.)

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ❌ blocker | no grain test — add unique_combination_of_columns (or unique) naming the grain | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | ❌ warning | mart has no enforced contract — add contract: {enforced: true} to pin its shape | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (rule applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `supplies` — model (layer `marts`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (0): —
- Tests present: none
- Contract enforced: `False`
- Inferred PK: (none identifiable)
- Key (`*_id`/`*_uuid`) columns beyond the PK: none
- ⚠️ **No columns declared in this model's YAML** — so the key-based rules (EN-*) below report _n/a_ not because the model has no keys, but because none are declared to evaluate. Declaring columns is itself the first gap to close. (Columns here are YAML-declared, from the manifest — not warehouse-resolved.)

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ❌ blocker | no grain test — add unique_combination_of_columns (or unique) naming the grain | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | ✅ yes | applies_when: _Model is a published/consumed mart or has downstream/external consumers._ | ❌ warning | mart has no enforced contract — add contract: {enforced: true} to pin its shape | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (rule applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `stg_customers` — model (layer `staging`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (1): `customer_id`
- Tests present: `not_null(customer_id)`, `relationships(customer_id)`, `unique(customer_id)`
- Contract enforced: `False`
- Inferred PK: `customer_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: none

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (rule applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | customer_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `stg_locations` — model (layer `staging`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (1): `location_id`
- Tests present: `not_null(location_id)`, `unique(location_id)`
- Contract enforced: `False`
- Inferred PK: `location_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: none

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (rule applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | location_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `stg_order_items` — model (layer `staging`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (2): `order_item_id`, `order_id`
- Tests present: `not_null(order_id)`, `not_null(order_item_id)`, `relationships(order_id)`, `unique(order_item_id)`
- Contract enforced: `False`
- Inferred PK: (none identifiable)
- Key (`*_id`/`*_uuid`) columns beyond the PK: `order_item_id`, `order_id`

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (rule applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (rule applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | ✅ yes | applies_when: _Column is a foreign key used in a JOIN ON to another model._ | ❌ warning | FK column(s) without a relationships test: order_item_id | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `stg_orders` — model (layer `staging`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (1): `order_id`
- Tests present: `dbt_utils.expression_is_true`, `not_null(order_id)`, `relationships(order_id)`, `unique(order_id)`
- Contract enforced: `False`
- Inferred PK: `order_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: none

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (rule applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | order_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `stg_products` — model (layer `staging`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (1): `product_id`
- Tests present: `not_null(product_id)`, `unique(product_id)`
- Contract enforced: `False`
- Inferred PK: `product_id`
- Key (`*_id`/`*_uuid`) columns beyond the PK: none

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (rule applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | product_id has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `stg_supplies` — model (layer `staging`)

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (1): `supply_uuid`
- Tests present: `not_null(supply_uuid)`, `unique(supply_uuid)`
- Contract enforced: `False`
- Inferred PK: `supply_uuid`
- Key (`*_id`/`*_uuid`) columns beyond the PK: none

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | ✅ yes | applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._ | ✅ pass | has a uniqueness/grain test | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | —  no | role/precondition not met (rule applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (rule applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | ✅ yes | applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._ | ✅ pass | supply_uuid has unique + not_null | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

## Sources

### `raw_customers` — source

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (0): —
- Tests present: none
- Declares a freshness SLA: `False`

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | —  no | role/precondition not met (rule applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | ✅ yes | applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._ | ❌ blocker | source has no freshness: block — add loaded_at_field + warn_after/error_after | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (rule applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (rule applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `raw_items` — source

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (0): —
- Tests present: none
- Declares a freshness SLA: `False`

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | —  no | role/precondition not met (rule applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | ✅ yes | applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._ | ❌ blocker | source has no freshness: block — add loaded_at_field + warn_after/error_after | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (rule applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (rule applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `raw_orders` — source

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (0): —
- Tests present: none
- Declares a freshness SLA: `False`

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | —  no | role/precondition not met (rule applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | ✅ yes | applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._ | ❌ blocker | source has no freshness: block — add loaded_at_field + warn_after/error_after | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (rule applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (rule applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `raw_products` — source

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (0): —
- Tests present: none
- Declares a freshness SLA: `False`

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | —  no | role/precondition not met (rule applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | ✅ yes | applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._ | ❌ blocker | source has no freshness: block — add loaded_at_field + warn_after/error_after | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (rule applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (rule applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `raw_stores` — source

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (0): —
- Tests present: none
- Declares a freshness SLA: `False`

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | —  no | role/precondition not met (rule applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | ✅ yes | applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._ | ❌ blocker | source has no freshness: block — add loaded_at_field + warn_after/error_after | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (rule applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (rule applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

### `raw_supplies` — source

**Manifest facts** (the source of every verdict below — from `target/manifest.json`):

- Columns (0): —
- Tests present: none
- Declares a freshness SLA: `False`

**Deterministically-evaluated rules** (code-proven; each row = a detector run over the facts above):

| Rule | DAMA-UK6 | Applies? | Why it does / doesn't apply | Verdict | Evidence (manifest fact) | Detector (code lineage) |
|---|---|---|---|---|---|---|
| `MD-01` | Uniqueness | —  no | role/precondition not met (rule applies_when: _ALWAYS — every model must name and test its grain. Flag any model missing it._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md01` — MD-01 grain-test: every MODEL must carry a model-level grain/uniqueness test. |
| `TM-AU-01` | Timeliness | ✅ yes | applies_when: _Column is loaded_at / an audit timestamp, or the model has an upstream source to monitor._ | ❌ blocker | source has no freshness: block — add loaded_at_field + warn_after/error_after | `adaf.taxonomy._detect_tmau01` — TM-AU-01 freshness: every SOURCE must declare a freshness block. |
| `MD-02` | Validity | —  no | role/precondition not met (rule applies_when: _Model is a published/consumed mart or has downstream/external consumers._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_md02` — MD-02 contracts (hybrid): a mart model should enforce a contract. Precondition = lives in marts/. |
| `EN-01` | Uniqueness/Completeness | —  no | role/precondition not met (rule applies_when: _Column is the single-column grain (PK/surrogate) of a dim/fact, or a JOIN key downstream._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en01` — EN-01 unique-key (hybrid): the model's PK column should have unique + not_null. |
| `EN-03` | Consistency | —  no | role/precondition not met (rule applies_when: _Column is a foreign key used in a JOIN ON to another model._) | n/a | detector returned no finding for this node | `adaf.taxonomy._detect_en03` — EN-03 FK-integrity (hybrid): non-PK ``*_id`` columns should have a relationships test. |

## Rules requiring judgement (NOT asserted per-model here)

These rules have no deterministic detector — their applicability depends on column semantics or intent that the manifest cannot prove (e.g. *is this column a ratio?*, *is this a refactor?*). To avoid hallucinating, this report does **not** assign them per-model verdicts. Their catalogue `applies_when` is listed below; the LLM `adaf review` is the (advisory, non-deterministic) source for model-by-model judgement on these — see the coverage matrices it posts to the PR.

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
| `TM-SC-03` | Validity | hybrid | A datetime column's TZ semantics matter and could drift between TIMESTAMP and DATETIME. |
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
