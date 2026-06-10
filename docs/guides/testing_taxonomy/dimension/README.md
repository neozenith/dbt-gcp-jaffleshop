# Role: dimension

| informal | Kimball | MetricFlow | Data Vault | Anchor |
| --- | --- | --- | --- | --- |
| Dimensional | Dimension attribute / junk dim | `dimension (categorical)` | Satellite attribute | Attribute / Knot |

A **dimension column** is a column that appears in a `GROUP BY` clause anywhere in the DAG. Status fields, categories, regions, boolean flags, low-cardinality codes. The defining test is "if a new value silently appears here, does any downstream `CASE` statement, dashboard bucket, or segmentation rule miss it?".

## Vignette index

1. **DM-01** · [`DM-01-accepted-values.md`](./DM-01-accepted-values.md) — enum contract on a categorical
2. **DM-02** · [`DM-02-cardinality-guard.md`](./DM-02-cardinality-guard.md) — `expect_column_unique_value_count_to_be_between`
3. **DM-04** · [`DM-04-mutual-exclusivity.md`](./DM-04-mutual-exclusivity.md) — sibling boolean flags do not co-fire
4. **DM-03** · [`DM-03-conformed-dimension.md`](./DM-03-conformed-dimension.md) — shared seed governs values across models
5. **DM-05** · [`DM-05-dimension-anomalies.md`](./DM-05-dimension-anomalies.md) — Elementary per-dimension count anomalies

## What can go wrong

| Failure mode | Symptom | Vignette |
|--------------|---------|----------|
| Unexpected new category | A new value silently sneaks in; downstream CASE statements miss it; metrics drift | [`DM-01-accepted-values.md`](./DM-01-accepted-values.md) |
| Cardinality explosion | A "low-cardinality" column suddenly has 10K values (CRM enabled free-text); GROUP BY explodes | [`DM-02-cardinality-guard.md`](./DM-02-cardinality-guard.md) |
| Mutual-exclusivity violation | `is_active=TRUE AND is_archived=TRUE` for one entity; sum across segments > 100% | [`DM-04-mutual-exclusivity.md`](./DM-04-mutual-exclusivity.md) |
| Conformed-dimension drift | "Region" reports show 5 buckets because two source systems disagree on the canonical 4 | [`DM-03-conformed-dimension.md`](./DM-03-conformed-dimension.md) |
| Per-dimension anomaly | One country drops to zero events while overall row count looks fine | [`DM-05-dimension-anomalies.md`](./DM-05-dimension-anomalies.md) |
| NULL where business rule says "must have one" | Reports show an "Unknown" bucket; segmentation breaks | covered in [`DM-01-accepted-values.md`](./DM-01-accepted-values.md) |
| Casing / whitespace drift | "USA" / "usa" / " USA " all coexist; GROUP BY produces three rows for one logical value | covered in [`DM-01-accepted-values.md`](./DM-01-accepted-values.md) |

## Anti-pattern: `accepted_values` only at the mart layer

The earlier you place `accepted_values`, the faster the failure surfaces. Apply at the **staging** layer (closest to ingestion) so a new source-side category fires within minutes, not after a 4-hour mart rebuild. See F.2 (The Quiet New Category) in the [taxonomy research](../README.md).

## Anti-pattern: Booleans modelled as strings

`status = 'active'` and `is_active = TRUE` are testable differently. Booleans accept three states (TRUE / FALSE / NULL), and downstream `WHERE flag = TRUE` silently drops the NULL bucket. Either declare the boolean strictly (`accepted_values: [true, false]` + `not_null`) or model the third state explicitly as an enum. Never let a "boolean-ish" string column slide.

## Cardinality is a dimension's identity

A column with 10 distinct values is a dimension. A column with 10 million distinct values is an entity. The line between the two roles is cardinality; when cardinality drifts, the column has changed role. The `cardinality-guard` test alerts when a dimension is sliding into entity territory. See [`DM-02-cardinality-guard.md`](./DM-02-cardinality-guard.md).
