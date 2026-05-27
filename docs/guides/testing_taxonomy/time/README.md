# Role: time

> **Synonyms:** Temporal (your brief) · Date dimension + fact event timestamp (Kimball) · `dimension (time)` (MetricFlow) · `load_date` (Data Vault) · `ChangedAt` (Anchor Modeling)
>
> **Hue:** Orange · **Primary fill:** `#ea580c` · **Stroke:** `#c2410c` · **Subgraph fill:** `#fff7ed`

A **time column** is a date / datetime / timestamp column. Its tests depend critically on the **sub-role** the column plays — three sub-roles, three different test suites.

## The three sub-roles

| Sub-role | Used in | Example | Vignette focus |
|----------|---------|---------|----------------|
| **Event-time scalar** | `WHERE`, arithmetic (`shipped_at - ordered_at`), window functions | `event_at`, `ordered_at`, `shipped_at` | [`event-time-bounds.md`](./event-time-bounds.md), [`monotonic-pair.md`](./monotonic-pair.md), [`timezone-contract.md`](./timezone-contract.md) |
| **Time-grain dimension** | `GROUP BY DATE_TRUNC('month', ...)`, joins to a calendar/date dim | `event_date`, `report_month` | [`calendar-spine.md`](./calendar-spine.md) |
| **System-time / audit** | SCD2 effectivity, freshness checks, ingest auditing | `loaded_at`, `valid_from`, `valid_to`, `dbt_updated_at` | [`freshness-source-and-model.md`](./freshness-source-and-model.md), [`scd2-quartet.md`](./scd2-quartet.md) |

A single physical column may play **multiple sub-roles** — `order_date` is often event-time-scalar (used in `created_at - order_date`), time-grain-dimensional (`GROUP BY order_date`), and a join key to `dim_date`. Apply the union of the relevant suites.

## What can go wrong

| Failure mode | Sub-role | Vignette |
|--------------|----------|----------|
| Future dates (`event_at > NOW()`) | scalar | [`event-time-bounds.md`](./event-time-bounds.md) |
| Sentinel dates (`1900-01-01`, `9999-12-31`) | scalar | [`event-time-bounds.md`](./event-time-bounds.md) |
| Monotonicity violation (`shipped_at < ordered_at`) | scalar pair | [`monotonic-pair.md`](./monotonic-pair.md) |
| Timezone confusion (TIMESTAMP_NTZ assumed UTC) | scalar | [`timezone-contract.md`](./timezone-contract.md) |
| Date vs datetime type mixing | scalar | [`timezone-contract.md`](./timezone-contract.md), [`../entity/type-stable-join.md`](../entity/type-stable-join.md) |
| Gaps in expected sequence | dimension | [`calendar-spine.md`](./calendar-spine.md) |
| Stale source (no new rows for X hours) | system-time | [`freshness-source-and-model.md`](./freshness-source-and-model.md) |
| SCD2 overlap / gap | system-time | [`scd2-quartet.md`](./scd2-quartet.md) |
| Ingest-time vs event-time confusion | scalar + system-time | [`event-time-bounds.md`](./event-time-bounds.md) |

## The four cardinal time anti-patterns

1. **Storing dates as strings.** `'2024-01-15'` as VARCHAR lexicographically sorts before `'2024-1-15'`. Use the typed `DATE`/`TIMESTAMP` family. Catch via `data_type` contract.
2. **Naive datetime in a TZ-aware column.** Populating `TIMESTAMPTZ` from a `TIMESTAMP` source silently assumes the session TZ. Catch via contract + cross-session test.
3. **Filtering on `loaded_at` when you mean `event_at`.** Late-arriving data bucketed by load day instead of event day. Catch via naming convention + `expression_is_true: loaded_at >= event_at`.
4. **Using `9999-12-31` or `1900-01-01` as a NULL substitute.** Sorts to extremes; sentinel ends up in `MIN()`/`MAX()` aggregates. Catch via `not_accepted_values`.

## Vignette index

1. [`event-time-bounds.md`](./event-time-bounds.md) — no future, no `1900-01-01` / `9999-12-31` sentinels
2. [`monotonic-pair.md`](./monotonic-pair.md) — `shipped_at >= ordered_at`, `updated_at >= created_at`
3. [`freshness-source-and-model.md`](./freshness-source-and-model.md) — source freshness + model recency
4. [`calendar-spine.md`](./calendar-spine.md) — `sequential_values` on `date_day`
5. [`scd2-quartet.md`](./scd2-quartet.md) — the four tests every Type-2 dim needs together
6. [`timezone-contract.md`](./timezone-contract.md) — TIMESTAMP vs DATETIME on BigQuery
