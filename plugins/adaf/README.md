# ADAF plugin

Agent skills over the **Automated Data Assurance Framework**.
This repository is both the [marketplace](../../.claude-plugin/marketplace.json) and the plugin host.

## Install

```bash
/plugin marketplace add neozenith/dbt-gcp-jaffleshop          # or:  /plugin marketplace add ./
/plugin install adaf@dbt-gcp-jaffleshop
```

## Skills

| Skill | Invoke | What it does |
|-------|--------|--------------|
| [`adaf-testing-guide`](skills/adaf-testing-guide/SKILL.md) | `/adaf:adaf-testing-guide` | Help a developer decide which data-quality tests a scope of dbt models should have and implement them correctly. Navigates the testing-taxonomy vignettes in `references/`, explains each test (why it matters, which package, DAMA-UK6 dimension, cost class), and grounds the implementation in current practice via web search. |

The `adaf-testing-guide` skill is **reference-driven**: it reads the testing-taxonomy vignettes bundled
under its own [`references/`](skills/adaf-testing-guide/references/testing_taxonomy/) and uses web search
to confirm current syntax.
