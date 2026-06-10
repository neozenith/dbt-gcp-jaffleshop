# Role: model-level

> **Synonyms:** Cross-column / whole-table tests · "structural" tests · "governance" tests

Tests in this folder do not belong to a single column — they assert properties of the model **as a whole**. They are the governance and structural layer of the taxonomy: the grain test that every model needs, contracts that lock the schema shape, versioning that lets the schema evolve safely, parity checks for refactors, and anomaly detectors that watch the model's volume and freshness.

## What can go wrong

| Failure mode | Vignette |
|--------------|----------|
| Model is silently a different grain than what the description says | [`MD-01-grain-test.md`](./MD-01-grain-test.md) |
| A column was renamed/retyped upstream; downstream silently breaks | [`MD-02-contracts.md`](./MD-02-contracts.md) |
| A public model's column was renamed and a Tableau dashboard broke without warning | [`MD-03-versioning-cutover.md`](./MD-03-versioning-cutover.md) |
| A refactor of a mart changes its output in subtle ways and nobody can prove parity | [`MD-04-refactor-parity.md`](./MD-04-refactor-parity.md) |
| A `CASE WHEN` regression bucketed an edge case incorrectly and no test caught it | [`MD-05-unit-tests.md`](./MD-05-unit-tests.md) |
| The table row count is "fine" but quietly halved over a month | [`MD-06-row-count-band.md`](./MD-06-row-count-band.md), [`MD-07-volume-anomaly.md`](./MD-07-volume-anomaly.md) |
| An upstream source you don't own added/dropped/retyped a column and your contract never saw it | [`MD-08-schema-changes.md`](./MD-08-schema-changes.md) |
| A column's null rate / average / zero-count drifted, but no per-column rule was watching it | [`MD-09-column-anomalies.md`](./MD-09-column-anomalies.md) |
| A JSON / semi-structured column lost a key or changed a nested type; the parse-time contract can't see inside it | [`MD-10-json-schema.md`](./MD-10-json-schema.md) |

## Defence in depth: shape AND content

dbt's three governance features — **contracts**, **versions**, **groups/access** — work at the *schema layer*. They are about **what shape** a model has. dbt's data tests work at the *content layer*. They are about **what values** the rows contain.

You need **both**:

- **Contracts** catch a column renamed or retyped upstream — at parse time, before any DDL.
- **Data tests** catch values drifting within an unchanged shape — at runtime, after the build.

On BigQuery specifically: only the `not_null` constraint is enforced at DDL. `primary_key`, `foreign_key`, `unique`, and `check` are all informational on BQ. That means **on BigQuery, contracts do not replace `unique` / `relationships` / range tests** — they declare intent, and the tests do the actual validation. See [`MD-02-contracts.md`](./MD-02-contracts.md) for the full BQ matrix.

## When versioning matters

Versioning is governance overhead. Reach for it only when:

1. The model is `access: public` (or cross-team `protected`).
2. The change is **breaking** — column removed/renamed, type changed, grain changed, nullability tightened.
3. There are consumers outside your immediate team.

For internal / staging / intermediate models — just refactor. dbt explicitly recommends bumping versions **only ~1–2× per year per public model**, not opportunistically. See [`MD-03-versioning-cutover.md`](./MD-03-versioning-cutover.md).

## Refactor parity

The hardest-to-prove claim during a refactor is "this model returns the same rows as before". `audit_helper`'s `compare_and_classify_relation_rows` (and its query-form sibling) is the canonical tool — it distinguishes `identical` / `modified` / `added` / `removed` / `nonunique_pk` row classifications, which earlier comparators (`compare_relations`, `compare_queries`) could not. See [`MD-04-refactor-parity.md`](./MD-04-refactor-parity.md).

## Vignette index

1. **MD-01** · [`MD-01-grain-test.md`](./MD-01-grain-test.md) — the one test every model must have
2. **MD-02** · [`MD-02-contracts.md`](./MD-02-contracts.md) — `contract.enforced: true` (shape, not content)
3. **MD-03** · [`MD-03-versioning-cutover.md`](./MD-03-versioning-cutover.md) — ship `v=N+1` without breaking consumers
4. **MD-04** · [`MD-04-refactor-parity.md`](./MD-04-refactor-parity.md) — `audit_helper.compare_and_classify_relation_rows`
5. **MD-05** · [`MD-05-unit-tests.md`](./MD-05-unit-tests.md) — dbt 1.8 unit tests for branching SQL logic
6. **MD-06** · [`MD-06-row-count-band.md`](./MD-06-row-count-band.md) — `expect_table_row_count_to_be_between`
7. **MD-07** · [`MD-07-volume-anomaly.md`](./MD-07-volume-anomaly.md) — Elementary volume anomaly detection
8. **MD-08** · [`MD-08-schema-changes.md`](./MD-08-schema-changes.md) — Elementary schema-change / baseline-drift detection on sources you don't own
9. **MD-09** · [`MD-09-column-anomalies.md`](./MD-09-column-anomalies.md) — Elementary automated column monitors (null %, min/max/avg, zero-count)
10. **MD-10** · [`MD-10-json-schema.md`](./MD-10-json-schema.md) — Elementary JSON-shape validation on semi-structured columns
