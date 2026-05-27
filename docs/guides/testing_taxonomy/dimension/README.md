# Role: dimension

> **Synonyms:** Dimensional (your brief) · Dimension attribute / junk dim (Kimball) · `dimension (categorical)` (MetricFlow) · Satellite attribute (Data Vault) · Attribute / Knot (Anchor)
>
> **Hue:** Violet · **Primary fill:** `#7c3aed` · **Stroke:** `#6d28d9` · **Subgraph fill:** `#ede9fe`

A **dimension column** is a column that appears in a `GROUP BY` clause anywhere in the DAG. Status fields, categories, regions, boolean flags, low-cardinality codes. The defining test is "if a new value silently appears here, does any downstream `CASE` statement, dashboard bucket, or segmentation rule miss it?".

## What can go wrong

| Failure mode | Symptom | Vignette |
|--------------|---------|----------|
| Unexpected new category | A new value silently sneaks in; downstream CASE statements miss it; metrics drift | [`accepted-values.md`](./accepted-values.md) |
| Cardinality explosion | A "low-cardinality" column suddenly has 10K values (CRM enabled free-text); GROUP BY explodes | [`cardinality-guard.md`](./cardinality-guard.md) |
| Mutual-exclusivity violation | `is_active=TRUE AND is_archived=TRUE` for one entity; sum across segments > 100% | [`mutual-exclusivity.md`](./mutual-exclusivity.md) |
| Conformed-dimension drift | "Region" reports show 5 buckets because two source systems disagree on the canonical 4 | [`conformed-dimension.md`](./conformed-dimension.md) |
| Per-dimension anomaly | One country drops to zero events while overall row count looks fine | [`dimension-anomalies.md`](./dimension-anomalies.md) |
| NULL where business rule says "must have one" | Reports show an "Unknown" bucket; segmentation breaks | covered in [`accepted-values.md`](./accepted-values.md) |
| Casing / whitespace drift | "USA" / "usa" / " USA " all coexist; GROUP BY produces three rows for one logical value | covered in [`accepted-values.md`](./accepted-values.md) |

## Anti-pattern: `accepted_values` only at the mart layer

The earlier you place `accepted_values`, the faster the failure surfaces. Apply at the **staging** layer (closest to ingestion) so a new source-side category fires within minutes, not after a 4-hour mart rebuild. See F.2 (The Quiet New Category) in the [taxonomy research](../README.md).

## Anti-pattern: Booleans modelled as strings

`status = 'active'` and `is_active = TRUE` are testable differently. Booleans accept three states (TRUE / FALSE / NULL), and downstream `WHERE flag = TRUE` silently drops the NULL bucket. Either declare the boolean strictly (`accepted_values: [true, false]` + `not_null`) or model the third state explicitly as an enum. Never let a "boolean-ish" string column slide.

## Cardinality is a dimension's identity

A column with 10 distinct values is a dimension. A column with 10 million distinct values is an entity. The line between the two roles is cardinality; when cardinality drifts, the column has changed role. The `cardinality-guard` test alerts when a dimension is sliding into entity territory. See [`cardinality-guard.md`](./cardinality-guard.md).

## Vignette index

1. [`accepted-values.md`](./accepted-values.md) — enum contract on a categorical
2. [`cardinality-guard.md`](./cardinality-guard.md) — `expect_column_unique_value_count_to_be_between`
3. [`mutual-exclusivity.md`](./mutual-exclusivity.md) — sibling boolean flags do not co-fire
4. [`conformed-dimension.md`](./conformed-dimension.md) — shared seed governs values across models
5. [`dimension-anomalies.md`](./dimension-anomalies.md) — Elementary per-dimension count anomalies
