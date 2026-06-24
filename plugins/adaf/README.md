# ADAF plugin

Agent skills over the **Automated Data Assurance Framework**.
This repository is both the [marketplace](../../.claude-plugin/marketplace.json) and the plugin host.

The skill itself is the portable [agentskills.io](https://agentskills.io/specification) `SKILL.md` format,
so it works across Claude Code, GitHub Copilot, and OpenAI Codex. The plugin ships **two parallel
manifests** over one shared `skills/` tree — [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json)
for Claude Code and [`.codex-plugin/plugin.json`](.codex-plugin/plugin.json) for Codex.

## Install

**Claude Code** — marketplace install:

```bash
/plugin marketplace add neozenith/dbt-gcp-jaffleshop          # or:  /plugin marketplace add ./
/plugin install adaf@dbt-gcp-jaffleshop
```

**OpenAI Codex** — installable plugin (`.codex-plugin/plugin.json` + bundled `skills/`), or zero-install
loose discovery: Codex scans `.agents/skills/` from the cwd up to the repo root and follows symlinks, so
the [`.agents/skills/adaf-testing-guide`](../../.agents/skills/adaf-testing-guide) symlink is picked up
with no install.

**GitHub Copilot** — scans `.github/skills`, `.claude/skills`, and `.agents/skills`; the same
`.agents/skills/` symlink is discovered automatically. (Copilot has no plugin-bundle manifest; `gh skill`
is its distribution path.)

## Skills

| Skill | Invoke | What it does |
|-------|--------|--------------|
| [`adaf-testing-guide`](skills/adaf-testing-guide/SKILL.md) | `/adaf:adaf-testing-guide` | Help a developer decide which data-quality tests a scope of dbt models should have and implement them correctly. Navigates the testing-taxonomy vignettes in `references/`, explains each test (why it matters, which package, DAMA-UK6 dimension, cost class), and grounds the implementation in current practice via web search. |

The `adaf-testing-guide` skill is **reference-driven**: it reads the testing-taxonomy vignettes bundled
under its own [`references/`](skills/adaf-testing-guide/references/testing_taxonomy/) and uses web search
to confirm current syntax.
