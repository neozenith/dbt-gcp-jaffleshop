# `adaf-ci` — per-job bootstrap (composite action)

The shared first step of every job in the adaf reusable workflow: authenticate to GCP (Workload
Identity Federation), set up the `uv`/`dbt` environment, and optionally restore the setup job's parsed
manifest + defer-state artifacts so a downstream job reuses them instead of rebuilding.

**Checkout first.** A local `uses: ./.github/actions/adaf-ci` needs the repo already present, so the
calling job must run `actions/checkout` BEFORE this action.

## Inputs

| Input | Required | Default | Purpose |
|-------|----------|---------|---------|
| `wif-provider` | yes | — | Workload Identity Federation provider for `google-github-actions/auth`. |
| `wif-sa` | yes | — | Service account to impersonate via WIF. |
| `download-state` | no | `'false'` | `'true'` restores the `adaf-manifest` (`target/`) and `adaf-defer-state` (`tmp/adaf_cache/defer/`) artifacts the setup job uploaded, so `adaf --defer-ref` hits the cache rather than rebuilding the baseline. `'false'` for the setup job itself. |

## Managed asset

Owned by the `adaf` CLI and deployed by `adaf gha init`; the `# adaf:managed version=…` banner records
the version. Edit the source under `adaf/gha/assets/actions/adaf-ci/`, not the deployed copy — the next
`gha init` overwrites local edits.
