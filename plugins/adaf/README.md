# ADAF plugin

Agent skills over the **Automated Data Assurance Framework** ([`.github/cli/adaf`](../../.github/cli/adaf/)).
This repository is both the [marketplace](../../.claude-plugin/marketplace.json) and the plugin host.

## Install

```bash
/plugin marketplace add neozenith/dbt-gcp-jaffleshop          # or:  /plugin marketplace add ./
/plugin install adaf@dbt-gcp-jaffleshop
```

## Skills

| Skill | Invoke | What it does |
|-------|--------|--------------|
| [`adaf-taxonomy-gaps`](skills/adaf-taxonomy-gaps/SKILL.md) | `/adaf:adaf-taxonomy-gaps` | Detect dbt testing-taxonomy / data-quality test gaps, explain each with its DAMA-UK6 dimension and how to suppress false positives, and (on request) apply **git-reversible** fixes. |

The skills drive the `adaf` CLI (`adaf check taxonomy`, `adaf review`, `adaf rules`) — the catalogue
of 33 rules is the single source of truth, so the skill, the CLI, and CI all agree on what a gap is.
