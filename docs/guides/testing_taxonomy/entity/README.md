# Role: entity

> **Synonyms:** Identity (informal) · Surrogate/natural key (Kimball) · `entity` (MetricFlow) · Hub/Link key (Data Vault) · Anchor/Tie (Anchor Modeling)
>
> **Hue:** Blue · **Primary fill:** `#2563eb` · **Stroke:** `#1e40af` · **Subgraph fill:** `#dbeafe`

An **entity column** is a column that appears in a `JOIN ... ON` clause anywhere in the DAG. Primary keys, foreign keys, surrogate keys, natural business keys, composite-key components — all entity. The defining test is "would a duplicate or mismatch here fan out a downstream join?".

## What can go wrong

| Failure mode | Symptom | Vignette |
|--------------|---------|----------|
| Duplicate keys | Downstream joins fanout; aggregates double | [`unique-key.md`](./unique-key.md), [`compound-grain.md`](./compound-grain.md) |
| NULL keys | Inner joins silently drop rows; left joins lump into a NULL bucket | [`unique-key.md`](./unique-key.md) (the not_null half) |
| Orphan foreign keys (FK with no matching PK upstream) | LEFT JOIN returns NULL on joined columns; metric undercounts | [`foreign-key-integrity.md`](./foreign-key-integrity.md) |
| Type mismatch across joined tables | Silent implicit cast on Snowflake; query failure on BigQuery; zero matches on Postgres | [`type-stable-join.md`](./type-stable-join.md) |
| Soft-deleted rows polluting the FK check | `relationships` passes against the unfiltered dim but join produces "Unknown" downstream | [`soft-delete-scoped-fk.md`](./soft-delete-scoped-fk.md) |
| Surrogate key collision (`MD5(a \|\| b)` without delimiter) | Two distinct logical events collide to one surrogate; `unique` passes by luck | [`surrogate-collision-guard.md`](./surrogate-collision-guard.md) |
| Composite key not deduped | Single-column `unique` passes, but the grain has duplicates | [`compound-grain.md`](./compound-grain.md) |

## Anti-pattern: Identity columns without `unique` + `not_null`

Pair `unique` and `not_null` on **every** entity column unless there's an explicit business reason not to. The cost of these tests is near-zero (single index-friendly aggregations on most warehouses); the cost of missing a duplicate is a CFO-visible incident. See [F.1](../README.md#the-two-heuristics) (Silent FK Fanout) for the cautionary tale.

## Anti-pattern: Conflating "the column has a unique constraint" with "the column is unique in this model"

On BigQuery, `primary_key` and `unique` constraints declared in a model `contract` are **informational only** — BQ does not enforce them at DDL time. The data test `unique` is what actually validates the content. The constraint declares intent; the test enforces it. See [`../model/contracts.md`](../model/contracts.md).

## Composite key (grain) rule

Every dbt model has exactly one `dbt_utils.unique_combination_of_columns` test that names its grain. The grain is a tuple of entity columns (sometimes plus a time column). If you can't name the grain, the model isn't done. See [`compound-grain.md`](./compound-grain.md) and [`../model/grain-test.md`](../model/grain-test.md).

## Cross-role intersections

Entity columns frequently double as dimensions (`order_id` is an entity in `dim_orders` but a `GROUP BY` axis in `mart_orders_by_customer`). When an entity also plays a dimensional role, the test suite is the **union** of both roles' suites. See the [Role Multiplication Heuristic](../README.md#2-the-role-multiplication-heuristic).

## Vignette index

1. **EN-01** · [`unique-key.md`](./unique-key.md) — single-column `unique` + `not_null`
2. **EN-02** · [`compound-grain.md`](./compound-grain.md) — `dbt_utils.unique_combination_of_columns`
3. **EN-03** · [`foreign-key-integrity.md`](./foreign-key-integrity.md) — `relationships`
4. **EN-04** · [`soft-delete-scoped-fk.md`](./soft-delete-scoped-fk.md) — `relationships_where`
5. **EN-06** · [`type-stable-join.md`](./type-stable-join.md) — contract `data_type` matches across joined relations
6. **EN-05** · [`surrogate-collision-guard.md`](./surrogate-collision-guard.md) — natural-key uniqueness alongside surrogate uniqueness
