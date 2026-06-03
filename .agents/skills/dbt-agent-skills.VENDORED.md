# Vendored: dbt-labs/dbt-agent-skills

The following agent skills are **vendored** (copied in, not a submodule) from the
official [dbt-labs/dbt-agent-skills](https://github.com/dbt-labs/dbt-agent-skills)
repository so agents working in this repo can review and manage the dbt project.

- **Upstream:** https://github.com/dbt-labs/dbt-agent-skills
- **Vendored at commit:** `2e412857db5099d668c303e589b38edd733da3be`
- **Vendored on:** 2026-06-03
- **Layout note:** upstream groups skills under `skills/<group>/skills/<skill>/`
  (`dbt`, `dbt-extras`, `dbt-migration`). They are flattened here to
  `.agents/skills/<skill>/` to match this repo's existing flat convention.

## Skills pulled in (12)

| Skill | Group |
|-------|-------|
| `using-dbt-for-analytics-engineering` | dbt |
| `building-dbt-semantic-layer` | dbt |
| `working-with-dbt-mesh` | dbt |
| `adding-dbt-unit-test` | dbt |
| `running-dbt-commands` | dbt |
| `troubleshooting-dbt-job-errors` | dbt |
| `fetching-dbt-docs` | dbt |
| `configuring-dbt-mcp-server` | dbt |
| `answering-natural-language-questions-with-dbt` | dbt |
| `creating-mermaid-dbt-dag` | dbt-extras |
| `migrating-dbt-core-to-fusion` | dbt-migration |
| `migrating-dbt-project-across-platforms` | dbt-migration |

> Project-local skills authored in this repo (e.g. `testing-taxonomy-review`) live
> alongside these but are **not** vendored — do not overwrite them on refresh.

## Refreshing

```bash
git clone --depth 1 https://github.com/dbt-labs/dbt-agent-skills tmp/dbt-agent-skills
for d in tmp/dbt-agent-skills/skills/*/skills/*/; do
  cp -R "$d" ".agents/skills/$(basename "$d")"
done
# then update the commit SHA + date above
```
