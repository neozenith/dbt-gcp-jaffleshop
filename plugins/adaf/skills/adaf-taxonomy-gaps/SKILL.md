---
name: adaf-taxonomy-gaps
description: >-
  Find and (on request) fix dbt testing-taxonomy / data-quality test gaps in dbt models using the
  ADAF CLI. Use when a developer asks to review a dbt model's tests, find missing data-quality tests
  (grain, uniqueness, freshness, contracts, FK integrity), check DAMA-UK6 coverage, or close
  taxonomy gaps before opening a PR. Each finding is explained with its DAMA-UK6 dimension and how to
  suppress it if it's a false positive; fixes are always applied git-reversibly and the intentionally
  -broken demo models are never silently "repaired".
allowed-tools: Bash, Read, Edit, Grep, Glob
---

# ADAF taxonomy-gap review

You drive the **ADAF CLI** (`adaf`) to find, explain, and optionally close data-quality test gaps in
dbt models. The catalogue of 33 rules (codes like `MD-01`, `TM-AU-01`, `EN-03`) is the single source
of truth — `adaf rules` is authoritative; never invent rule codes or dimensions.

## Ground rules (read first)

1. **Detect before you fix.** Always run the checks and present findings *before* changing anything.
2. **Fixes are opt-in and git-reversible.** Only modify files when the user explicitly asks you to
   fix. Touch only the YAML/SQL lines needed; never reformat unrelated content. Tell the user the
   exact `git` command to undo (`git checkout -- <files>` or `git stash`).
3. **Never silently "fix" the broken demo fixture.** This repo keeps some dbt models intentionally
   broken (`products`, `supplies`, `locations` missing tests; sources missing freshness; no
   contracts) to exercise these checks. Do not repair them unless the user asks for that specific
   model, and warn that doing so removes a test fixture.
4. **A finding may be a false positive.** The `hybrid` rules are heuristics. For every gap you
   report, state that it might not apply and show how to suppress it (see *Explain*).

## 1. Locate the project and run the checks

The dbt project is `dbt-jaffleshop/`; `adaf` is installed as a dev dependency, so run it through the
project's env (no `cd` — use `--directory`):

```bash
# Deterministic detectors (grain/freshness/contracts/keys) — fast, no warehouse, no LLM:
uv run --directory dbt-jaffleshop adaf check taxonomy --all --json
# Scope to the models changed on this branch instead of --all:
uv run --directory dbt-jaffleshop adaf check taxonomy --json
# The full deterministic gate suite (docs, tests, taxonomy, boundaries, lint, …):
uv run --directory dbt-jaffleshop adaf check all --all --json
```

For the **LLM judgement layer** (the `hybrid`/`llm` rules — applicability, FK intent, ratios, SCD2),
run the reviewer. It needs a GitHub token (`models: read`) and makes no changes:

```bash
GITHUB_TOKEN=$(gh auth token) uv run --directory dbt-jaffleshop adaf review --changed-only --json
```

Parse the JSON. For `check taxonomy`, each `results[]` row has `node`, `rule_code`, `severity`
(`blocker`/`warning`), `status` (`missing`/`present`), and a `detail` with the remediation. The
`suppressed[]` array lists gaps already opted out via `adaf.yml` / inline comments — do not re-flag
those.

## 2. Explain each finding

For every **missing** finding, give the developer:

- **What & why** — quote the `detail`, and the rule's DAMA-UK6 dimension and vignette:
  ```bash
  uv run --directory dbt-jaffleshop adaf rules show MD-02       # dimensions, framework ladder, vignette path
  ```
  Read the vignette (`docs/guides/testing_taxonomy/...`) for the worked pattern.
- **Confidence** — say plainly whether this is a hard `blocker` (deterministic; almost certainly a
  real gap) or a `warning` (hybrid heuristic; **may be a false positive**).
- **How to suppress it** (always include this for warnings):
  ```bash
  uv run --directory dbt-jaffleshop adaf rules explain MD-02    # prints the exact disable syntax
  ```
  The two ways are an inline `-- adaf-disable: MD-02 (reason)` comment in the model's `.sql`, or an
  `adaf.yml` entry with a path glob + reason. Recommend suppression (with a reason) over a fix when
  the rule genuinely doesn't apply.

## 3. Address (only when asked)

When the user asks you to fix a gap, apply the **smallest** change that satisfies the rule, following
the vignette's `framework_first` (the preference ladder dbt core → dbt-utils → dbt_expectations →
elementary → audit_helper). Typical fixes, by rule:

- **MD-01 grain-test** → add a `dbt_utils.unique_combination_of_columns` model-level test naming the
  grain (and document the grain in the model `description`).
- **TM-AU-01 freshness** → add a `freshness:` block (`loaded_at_field` + `warn_after`/`error_after`)
  to the source in `__sources.yml`.
- **MD-02 contracts** → add `config: { contract: { enforced: true } }` and ensure column `data_type`s
  are declared.
- **EN-01 / EN-03** → add `unique`+`not_null` to the PK column, or a `relationships` test to the FK.

After editing, re-run `adaf check taxonomy --json` to confirm the finding cleared, then show the user:
the diff (`git diff`), and the one-line undo (`git checkout -- <file>` or `git stash`). If the gap was
a deliberate demo fixture, prefer adding a **suppression with a reason** over a fix, and say so.

## 4. Report

Summarise as a short table: rule code · node · dimension · blocker/warning · recommended action
(fix / suppress / accept). End with the exact commands you ran so the developer can reproduce.

> You can be wrong: these detectors are deterministic for structure but heuristic for *applicability*.
> When in doubt, present the option (fix vs. suppress) and let the developer decide — the suppression
> escape hatch exists precisely so a false positive never blocks a PR.
