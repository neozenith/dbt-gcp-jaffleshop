# Role: measure

> **Synonyms:** Measure (informal) · Fact (Kimball: additive / semi-additive / non-additive) · `measure` (MetricFlow) · Transactional satellite attribute (Data Vault)
>
> **Hue:** Emerald · **Primary fill:** `#059669` · **Stroke:** `#047857` · **Subgraph fill:** `#d1fae5`

A **measure column** is a numeric column that appears inside an aggregate function — `SUM`, `COUNT`, `AVG`, `MIN`, `MAX` — somewhere in the DAG. Measures are the columns that *become* metrics. Their failure modes are the most subtle in the catalogue, because aggregation hides almost all data quality problems.

## The Kimball additivity sub-classification

Every measure is one of three types. The testing strategy differs by type — this is the single biggest decision in the measure role.

| Type | Example | Can be SUMmed across | Cannot be SUMmed across |
|------|---------|----------------------|-------------------------|
| **Additive** | `quantity`, `revenue_dollars`, `quantity_returned` | every dimension including time | (always safe to sum) |
| **Semi-additive** | `account_balance`, `inventory_on_hand`, `headcount` | most dimensions | **time** — use `LAST_VALUE` or `MAX(date)` instead of `SUM` |
| **Non-additive** | `unit_price`, `gross_margin_pct`, `conversion_rate` | **nothing** — must recompute from additive components | (never safe to sum) |

If a measure is semi-additive or non-additive and gets SUMmed at the wrong grain, the metric is silently catastrophically wrong (F.8 — Semi-Additive Inventory Sum). The test side alone can't fix this — see [`additivity-tag.md`](./additivity-tag.md).

## What can go wrong

| Failure mode | Symptom | Vignette |
|--------------|---------|----------|
| Negative values where positive expected (`quantity = -1`) | Sum understates revenue | [`numeric-range.md`](./numeric-range.md) |
| Outliers (`amount = 999,999,999`) | Mean and sum blown out by a single row | [`numeric-range.md`](./numeric-range.md), [`distribution-anomaly.md`](./distribution-anomaly.md) |
| Currency / unit drift (USD + MXN, both summed) | Catastrophic silent 100× errors | [`currency-pairing.md`](./currency-pairing.md) |
| Semi-additive measure summed across time | Inventory reported as 30× actual at month-end | [`additivity-tag.md`](./additivity-tag.md) |
| Non-additive measure summed at all | "Total" unit price reported = meaningless | [`additivity-tag.md`](./additivity-tag.md) |
| Distribution drift over time | Currency or unit changed; mean halves overnight | [`distribution-anomaly.md`](./distribution-anomaly.md) |
| NaN / Inf from divide-by-zero | NaN propagates through every SUM; one region disappears | [`nan-inf-guard.md`](./nan-inf-guard.md) |
| Precision loss (`FLOAT` instead of `DECIMAL` for money) | Reconciliation off by pennies; 0.1 + 0.2 ≠ 0.3 | covered in [`numeric-range.md`](./numeric-range.md) (contract side) |

## Cross-role concerns specific to measure

### Sum-equals-total reconciliation

`fct_orders.order_total` should equal `SUM(fct_order_items.line_total) GROUP BY order_id` for every order. This is a model-level reconciliation test that lives in [`../model/refactor-parity.md`](../model/refactor-parity.md) — but it's a measure concern at heart.

### Pair measure tests with the dimension that scopes them

A `non-negative quantity` test might be valid only when `transaction_type = 'sale'` (returns are negative by design). Scope via `where:`:

```yaml
- dbt_utils.accepted_range:
    min_value: 0
    config:
      where: "transaction_type = 'sale'"
```

## Vignette index

1. **MS-01** · [`numeric-range.md`](./numeric-range.md) — `accepted_range`, `expect_column_values_to_be_between`
2. **MS-02** · [`additivity-tag.md`](./additivity-tag.md) — additive / semi-additive / non-additive classification + semantic-layer enforcement
3. **MS-03** · [`currency-pairing.md`](./currency-pairing.md) — amount columns always travel with `currency_code`
4. **MS-05** · [`distribution-anomaly.md`](./distribution-anomaly.md) — mean/stdev anomaly detection
5. **MS-04** · [`nan-inf-guard.md`](./nan-inf-guard.md) — divide-by-zero, Inf, NaN traps
