# `adaf-cleanup` — PR dataset teardown (composite action)

Drops the PR-namespaced dataset created during a test run, so ephemeral per-PR datasets don't
accumulate in the warehouse.

## Inputs

| Input | Required | Default | Purpose |
|-------|----------|---------|---------|
| `target` | yes | — | The dbt target whose dataset is cleaned up (e.g. `dev`, `test`). |
| `pr-number` | yes | — | The PR number whose datasets to clean up. |
| `dry-run` | no | `'false'` | `'true'` only prints the datasets that would be deleted; `'false'` (default) actually deletes them. |

## Managed asset

Owned by the `adaf` CLI and deployed by `adaf gha init`; the `# adaf:managed version=…` banner records
the version. Edit the source under `adaf/gha/assets/actions/adaf-cleanup/`, not the deployed copy — the
next `gha init` overwrites local edits.
