---
name: adaf-taxonomy-gaps
description: >-
  Find and (on request) fix dbt testing-taxonomy / data-quality test gaps in any dbt project using the
  ADAF CLI. Use when a developer asks to review a dbt model's tests, find missing data-quality tests
  (grain, uniqueness, freshness, contracts, FK integrity), check DAMA-UK6 coverage, or close taxonomy
  gaps before opening a PR. Each finding is explained with its DAMA-UK6 dimension and how to suppress
  it if it's a false positive; fixes are always applied git-reversibly and models that look like
  deliberate test fixtures are never silently "repaired".
allowed-tools: Bash, Read, Edit, Grep, Glob
---

# ADAF taxonomy-gap review

You drive the **ADAF CLI** (`adaf`) to find, explain, and optionally close data-quality test gaps in
a dbt project. The catalogue of rules (codes like `MD-01`, `TM-AU-01`, `EN-03`) is the single source of
truth — `adaf rules` is authoritative; never invent rule codes or dimensions.

## Ground rules (read first)

1. **Detect before you fix.** Always run the checks and present findings *before* changing anything.
2. **Fixes are opt-in and git-reversible.** Only modify files when the user explicitly asks. Touch only
   the YAML/SQL lines needed; never reformat unrelated content. Tell the user the exact undo command
   (`git checkout -- <files>` or `git stash`).
3. **Never silently fix a deliberate fixture.** Some projects keep models intentionally incomplete to
   exercise CI / agent tooling (this plugin's own demo repo does). If a model looks like a fixture, do
   not repair it unless the user names that model, and warn that doing so removes a test fixture.
4. **A finding may be a false positive.** The `hybrid` rules are heuristics. For every gap, state that
   it might not apply and show how to suppress it (see *Explain*).

## 0. Locate the project and how to invoke `adaf`

Find the dbt project (the directory containing `dbt_project.yml`) and pick the invocation that works in
this repo — then pass `--project-dir` so `adaf` targets it regardless of your cwd:

```bash
PROJECT=$(cd "$(git rev-parse --show-toplevel)" && dirname "$(git ls-files '*dbt_project.yml' | head -1)")

# Choose ONE for $ADAF (try in order):
ADAF="adaf"                                              # installed on PATH (uv tool install / plugin)
ADAF="uv run --directory $PROJECT adaf"                  # adaf is a dev-dependency of the dbt project
ADAF="uvx --from <repo>/.github/cli/adaf adaf"           # run from the adaf source checkout
```

Verify with `$ADAF rules validate`. Every command below ends with `--project-dir "$PROJECT"`. (The
`uv run --directory` form already sets cwd to the project, so `--project-dir` is belt-and-braces there.)

## 1. Run the checks

```bash
# Deterministic detectors (grain/freshness/contracts/keys) — fast, no warehouse, no LLM:
$ADAF check taxonomy --all --json --project-dir "$PROJECT"
# Warehouse-resolved columns enrich key/time rules (needs a prior `dbt docs generate`):
$ADAF check taxonomy --all --catalog target/catalog.json --json --project-dir "$PROJECT"
# Only the models changed on this branch:
$ADAF check taxonomy --json --project-dir "$PROJECT"
# The full deterministic gate suite (docs, tests, taxonomy, boundaries, lint, …):
$ADAF check all --all --json --project-dir "$PROJECT"
```

For the **LLM judgement layer** (the `hybrid`/`llm` rules — applicability, FK intent, ratios, SCD2),
run the reviewer (needs a GitHub token with `models: read`; makes no changes):

```bash
GITHUB_TOKEN=$(gh auth token) $ADAF review --changed-only --json --project-dir "$PROJECT"
```

Parse the JSON. In `check taxonomy`, each `results[]` row has `node`, `rule_code`, `severity`
(`blocker`/`warning`), `status` (`missing`/`present`), and a `detail` with the remediation; the
`suppressed[]` array lists gaps already opted out (do not re-flag those).

To hand the developer a single reviewable artifact that reconciles the deterministic checks against the
LLM (the false-positive / false-negative surface), generate the report:

```bash
$ADAF report --all --catalog target/catalog.json --review review.json -o adaf-model-review.md --project-dir "$PROJECT"
```

## 2. Explain each finding

For every **missing** finding, give the developer:

- **What & why** — quote the `detail`, and the rule's DAMA-UK6 dimension + vignette path:
  `$ADAF rules show MD-02 --project-dir "$PROJECT"`. Read the vignette it names for the worked pattern.
- **Confidence** — a hard `blocker` (deterministic; almost certainly real) vs a `warning` (hybrid
  heuristic; **may be a false positive**).
- **How to suppress it** (always, for warnings) — `$ADAF rules explain MD-02 --project-dir "$PROJECT"`
  prints the exact syntax: an inline `-- adaf-disable: MD-02 (reason)` comment in the model's `.sql`, or
  an `adaf.yml` entry with a path glob + reason. Recommend suppression-with-a-reason over a fix when the
  rule genuinely doesn't apply.

## 3. Address (only when asked)

Apply the **smallest** change that satisfies the rule, following the vignette's `framework_first` (the
ladder dbt core → dbt-utils → dbt_expectations → elementary → audit_helper). Typical fixes:

- **MD-01 grain-test** → a `dbt_utils.unique_combination_of_columns` model-level test naming the grain
  (and document the grain in the model `description`).
- **TM-AU-01 freshness** → a `freshness:` block (`loaded_at_field` + `warn_after`/`error_after`) on the
  source.
- **MD-02 contracts** → `config: { contract: { enforced: true } }` + declared column `data_type`s.
- **EN-01 / EN-03** → `unique`+`not_null` on the PK, or a `relationships` test on the FK.

Re-run `$ADAF check taxonomy --json --project-dir "$PROJECT"` to confirm the finding cleared, then show
the diff (`git diff`) and the one-line undo. If the gap is a deliberate fixture, prefer a suppression
(with a reason) over a fix and say so.

## 4. Report

Summarise as a short table: rule (`code` + slug) · node · DAMA dimension · blocker/warning ·
recommended action (fix / suppress / accept). End with the exact commands you ran so the developer can
reproduce.

> You can be wrong: the detectors are deterministic for structure but heuristic for *applicability*.
> When in doubt, present the choice (fix vs. suppress) and let the developer decide — the suppression
> escape hatch exists precisely so a false positive never blocks a PR.
