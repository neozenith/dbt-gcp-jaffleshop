# dbt testing-taxonomy review (composite action)

A thin composite Action that reviews the dbt models in a pull request against the project's
**testing-taxonomy catalogue** and posts coverage-matrix PR comments (changed + all models) with
token usage and estimated cost. It calls an LLM via **GitHub Models** (keyless, using the workflow's
`GITHUB_TOKEN`) — no vendor API key, no plugin.

> **The engine moved.** All logic — the LLM prompt, the rule catalogue, the batching/cost/comment
> code — now lives in the `adaf` CLI at [`.github/cli/adaf`](../../cli/adaf/). This action is just a
> wrapper that runs `adaf review --post`. See the consolidated [ADAF guide](../../../docs/guides/adaf.md)
> and [ADR-0005](../../../docs/arch/adr-0005-adaf-automated-data-assurance-framework.md).

## Usage

```yaml
- uses: ./.github/actions/dbt-testing-taxonomy-review
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}   # needs models:read + pull-requests:write
    pr-number: ${{ github.event.pull_request.number }}
    base-sha: ${{ github.event.pull_request.base.sha }}
```

Run the same review locally (prints the matrix instead of posting):

```bash
GITHUB_TOKEN=$(gh auth token) uv run --directory dbt-jaffleshop adaf review --all
```

## Inputs

See [`action.yml`](./action.yml) — `github-token`, `pr-number`, `base-sha` (required); `project-dir`,
`model`, `models-endpoint`, `cost-per-1m-input`, `cost-per-1m-output` (optional, defaulted).

## For maintainers

The wrapper is `action.yml`; everything it invokes is maintained in
[`.github/cli/adaf/CLAUDE.md`](../../cli/adaf/CLAUDE.md).
