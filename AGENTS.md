# AGENTS.md

Cross-tool agent context for this repository (read by OpenAI Codex, GitHub Copilot, and other
AGENTS.md-aware agents). Claude Code additionally reads `CLAUDE.md` and `.claude/rules/`, which hold the
full project rules; this file is the portable breadcrumb, not a duplicate of them.

## What this repo is

A dbt + GCP (BigQuery) analytics project ("jaffleshop"), plus the **ADAF** (Automated Data Assurance
Framework) tooling for dbt data-quality testing.

## Agent Skills

Skills are auto-discovered from `.agents/skills/` (Codex + Copilot) and from the `adaf` plugin under
`plugins/adaf/` (Claude Code, via marketplace install). The `.agents/skills/` entries are symlinks to the
canonical plugin sources — single source of truth, no duplication.

| Skill | Reach for it when |
|-------|-------------------|
| [`adaf-testing-guide`](.agents/skills/adaf-testing-guide/SKILL.md) | A developer asks which data-quality tests a dbt model (or scope of models) should have, or how to implement a specific test (grain, uniqueness, freshness, foreign key, enum, numeric range, SCD2, anomaly). It routes to the right testing-taxonomy vignette, explains the why + which package, and grounds the syntax in current docs via web search. |

## Conventions an agent must respect

- **Python:** use `uv` (`uv run …`), never bare `python`/`pip`. Subdir projects: `uv run --directory <dir> …`.
- **TypeScript:** use `bun`, never `node`/`npm`.
- **Never `cd` away from the repo root** — use relative paths or `--directory`/`--cwd` flags. The
  `Makefile` is the command-and-control surface.
- **Temp files go in `tmp/`** at the repo root, never the system `/tmp`.
- **No CSV** as a data format unless explicitly required; prefer Parquet / DuckDB / JSON.
- Full rules: `CLAUDE.md` and `.claude/rules/`.
