# dbt Fusion (v2.0) parquet artifacts

Reference for the columnar metadata artifact set the dbt **Fusion** engine writes, and how
`adaf` reads it. This is the contract behind
[`adaf.dbt.artifact.ParquetManifestArtifact`](../src/adaf/dbt/artifact.py); read that class's
docstring for the in-code summary.

> **Verified against** real Fusion output `dbt-fusion 2.0.0-preview.190`, `dbt parse --write-index`.
> The schema is alpha and will churn — the reader pins this layout explicitly and **fails loudly**
> (naming the file + missing column) when a parquet file no longer matches, rather than degrading.

## What it is

dbt-core writes one `target/manifest.json` (the "v12" JSON manifest). The Fusion engine writes that
JSON manifest **and**, with `--write-index`, an additional columnar **parquet** metadata set under
`target/metadata/` — the "v20" artifact. The parquet set is the new format `adaf` exercises; both are
present after a Fusion parse, so any reader that wants the parquet path must prefer it explicitly.

Produce it:

```bash
dbt parse --write-index        # Fusion engine; writes target/metadata/parse/*.parquet
```

## On-disk layout

Relative to the dbt target dir (default `target/`):

| Path | Required | Contents |
|------|----------|----------|
| `metadata/parse/nodes/v1_0.parquet` | yes | One row per resource of EVERY `resource_type` (model, test, source, exposure, semantic_model, metric, macro, …). |
| `metadata/parse/test_metadata/v1_0.parquet` | no | Sidecar: each data test's `test_name` / `test_namespace`. |
| `metadata/parse/generation.parquet` | no | Best-effort run metadata; `adaf` reads only `project_name`. |

The presence of `metadata/parse/nodes/v1_0.parquet` is what distinguishes a Fusion artifact set from
a dbt-core one (which has only `manifest.json`).

## Node table schema (`nodes/v1_0.parquet`)

`adaf` projects an explicit column list (never `SELECT *`) — every Fusion artifact also carries an
`ingested_at` `TIMESTAMP WITH TIME ZONE` column the reader never touches (materialising it would pull
in `pytz`). The consumed columns:

| Column | Type | Used for |
|--------|------|----------|
| `unique_id` | VARCHAR | node key + section routing |
| `resource_type` | VARCHAR | which manifest section the row routes into |
| `name` | VARCHAR | display name |
| `package_name` | VARCHAR | root-project filter for `--macros` |
| `original_path` | VARCHAR | → `original_file_path` (git-changed join, schema anchoring) |
| `description` | VARCHAR | docs coverage |
| `tags` | VARCHAR[] | selector/tag display |
| `fqn` | VARCHAR[] | display |
| `depends_on` | VARCHAR[] | lineage — a flat list of parent ids (nodes AND macros) |
| `payload` | VARCHAR (JSON) | the rich node; see below |

`depends_on` is a single flat list; `adaf` splits it by the `macro.` id prefix into
`depends_on.{nodes, macros}` to match the manifest.json shape. `parent_map` is derived from the
`nodes`-only ids.

### The `payload` JSON blob

Per-projection extras the typed columns don't carry are read from `payload`:

| JSON path | Used by |
|-----------|---------|
| `__common_attr__.patch_path` | docs-coverage schema anchoring |
| `config` (`contract.enforced`) | the `sdag check` contract rule (MD-02) |
| `__base_attr__.columns[*].description` | per-column doc coverage |
| `__source_attr__.freshness` (sources only) | the freshness rule (TM-AU-01) |

## How `adaf` reads it

`ParquetManifestArtifact` rebuilds the `manifest.json` section layout from the one node table so
[`ManifestView`](../src/adaf/dbt/manifest_view.py) and every projection stay format-agnostic:

- Rows route to sections by `resource_type` (`source` → `sources`, `exposure` → `exposures`,
  `semantic_model` → `semantic_models`, `metric` → `metrics`, `macro` → `macros`, everything else →
  `nodes`).
- `metadata/parse/test_metadata/v1_0.parquet` is merged back onto each test node as `test_metadata`,
  so the Elementary volume-anomaly heuristic (MD-07) works identically to the JSON path.

`load_artifact(dir)` probes for `metadata/parse/nodes/v1_0.parquet` first and only then falls back to
`manifest.json` — so a Fusion target (which has both) exercises the parquet reader.

Reading the parquet set requires duckdb, installed via the optional extra:

```bash
pip install 'adaf[fusion]'      # or: uv run --extra fusion …
```

The import is feature-gated inside the reader: the JSON path never needs duckdb, and a missing duckdb
on the parquet path raises a clear `ImportError` pointing here — never a silent fall back to JSON.

## Test coverage

- [`tests/test_artifact.py`](../tests/test_artifact.py) synthesises this exact layout with duckdb
  (including the unused `ingested_at` tz column) and asserts the section routing, `depends_on` split,
  projection correctness, and the loud-failure paths. Run with `make test` (the target passes
  `--extra fusion` so these run rather than skip).
- The [`dbt-fusion` multiversion row](../tests/multiversion/README.md) runs the real Fusion engine in
  Docker and snapshots the gates against the parquet artifact it actually emits.
