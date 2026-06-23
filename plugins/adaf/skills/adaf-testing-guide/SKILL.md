---
name: adaf-testing-guide
description: >-
  Help a developer decide which data-quality tests to apply to a scope of dbt models, then implement
  them correctly. Use when someone asks "what tests should this model have?", "how do I test
  uniqueness / grain / freshness / a foreign key / an enum / a numeric range / SCD2 / an anomaly?",
  or wants to close test coverage on staging/marts before a PR. Walks the testing-taxonomy decision
  tree in references/, opens the matching vignette (the worked pattern + why it matters + which dbt
  package to reach for), and grounds the final implementation in current practice with a web search
  because vignette code samples and package recommendations date.
allowed-tools: Read, Grep, Glob, WebSearch, WebFetch
---

# ADAF testing guide

Help a developer answer two questions for a **scope of dbt models**: *which tests should these models
have?* and *how do I implement each one correctly?* You do this by navigating the **testing taxonomy**
under [`references/testing_taxonomy/`](references/testing_taxonomy/) — a catalogue of ~33 *vignettes*,
each a worked pattern with symptoms, mechanics, a framework-choice matrix, and a "when NOT to use".

This skill is **advisory and reference-driven**. There is no CLI, no detector, no JSON to parse. Your
sources of truth are the markdown files in `references/` plus a **web search** to confirm the current
syntax and package guidance before the developer writes code.

## How the references are organised (read this once)

- [`references/testing_taxonomy/README.md`](references/testing_taxonomy/README.md) — the **root**: the
  two categorisation heuristics, the decision tree, the framework matrix, cost classes, and the
  DAMA-UK6 dimension map. **Start here for any scoping question.**
- Five **role folders**, each with its own `README.md` index:
  [`model/`](references/testing_taxonomy/model/README.md) (whole-table concerns),
  [`entity/`](references/testing_taxonomy/entity/README.md) (JOIN keys),
  [`dimension/`](references/testing_taxonomy/dimension/README.md) (GROUP BY / WHERE axes),
  [`measure/`](references/testing_taxonomy/measure/README.md) (aggregated numbers),
  [`time/`](references/testing_taxonomy/time/README.md) (date / datetime / timestamp).
- **Vignettes** named by rule code: `MD-01-grain-test.md`, `EN-03-foreign-key-integrity.md`,
  `TM-AU-01-freshness-source-and-model.md`, etc. The code prefix encodes the role
  (`MD`=model, `EN`=entity, `DM`=dimension, `MS`=measure, `TM`=time; time sub-codes `SC`=scalar,
  `GR`=grain, `AU`=audit).
- [`templates/default.md`](references/testing_taxonomy/templates/default.md) — the shape every vignette
  follows, so you know where to find each part.

## The procedure

### 1. Pin the scope and the grain

Get the concrete model(s) in scope. Read each model's `.sql` and its `.yml`/`schema.yml` so you reason
about the real columns and existing tests, not guesses. For every model, **name its grain first** — the
tuple of columns that uniquely identifies a row (`order_id`; `order_id, line_number`;
`user_id, date_day`). The grain is the anchor for everything else; if it can't be named, that's the
first finding. See [`model/MD-01-grain-test.md`](references/testing_taxonomy/model/MD-01-grain-test.md).

### 2. Walk the decision tree per column / concern

For each thing worth testing, apply the **two heuristics** from the root README:

1. **Whole model or one column?** Grain, row-count band, contract, freshness, refactor parity →
   model-level ([`model/`](references/testing_taxonomy/model/README.md)). Otherwise it's a column.
2. **What semantic category is the column?** — by what it *does in SQL*, not its warehouse type:
   - appears in `JOIN … ON` → **entity** ([`entity/`](references/testing_taxonomy/entity/README.md))
   - appears in `GROUP BY` / `WHERE` → **dimension** ([`dimension/`](references/testing_taxonomy/dimension/README.md))
   - wrapped in `SUM`/`COUNT`/`AVG` → **measure** ([`measure/`](references/testing_taxonomy/measure/README.md))
   - a date / datetime / timestamp → **time** ([`time/`](references/testing_taxonomy/time/README.md))

   A column can answer **more than once** — `order_id` is both a join key and a GROUP BY axis. Take the
   **union** of the matching suites (root README, *Role multiplication*).

Open the relevant **role README** to turn the category into a shortlist of rule codes, then open the
specific **vignette** for each candidate test.

### 3. Index efficiently — don't read the whole catalogue

You rarely need more than a handful of vignettes. To find the right one fast:

- **Know the test, want the vignette?** Map intent → code via the root README's *Vignette index* and
  *Framework matrix*, then open that one file. e.g. "enum membership" → `DM-01`; "freshness" →
  `TM-AU-01`; "referential integrity" → `EN-03`; "refactor parity" → `MD-04`.
- **Searching by keyword?** `Grep` across `references/testing_taxonomy/` for the SQL construct or test
  name (`unique_combination_of_columns`, `relationships_where`, `accepted_range`, `freshness`).
- **Coverage sweep over a scope?** Read the five role READMEs' *What can go wrong* tables, not every
  vignette — they map failure modes to codes so you can spot which suites a model is missing.

### 4. Explain each recommendation from the vignette

For every test you recommend, give the developer the vignette's reasoning, not just a YAML snippet:

- **Why it matters** — the *Symptoms* (the production failure it prevents) and the *Pattern* statement.
- **Which package to reach for** — the vignette's *Framework choice* matrix. The taxonomy's preference
  ladder is **dbt core → dbt-utils → dbt_expectations → elementary → audit_helper**; climb only when a
  lower tier can't express the intent.
- **DAMA-UK6 dimension** — the data-quality dimension the test defends (Uniqueness, Completeness,
  Validity, Consistency, Accuracy, Timeliness), from the vignette header.
- **Cost class** — free / cheap / scan-bound / history-bound, so the developer sequences it into CI vs.
  nightly vs. on-demand.
- **When NOT to use** — quote the vignette's negative space so a test isn't added where it's overkill
  (passthrough `stg_*`, business-permitted sparsity, prohibitive scan cost).

### 5. Ground the implementation in current practice (web search)

The vignettes are dated worked examples — package names, syntax, and recommendations drift. **Before the
developer commits to a YAML/SQL implementation, run a web search to confirm the current state**, then
reconcile it against the vignette:

- **Always re-check when the vignette flags maintenance.** The catalogue notes `dbt_expectations` was
  marked unmaintained (2026-05). Verify whether the package the vignette names is still the right one,
  or whether a maintained replacement now exists.
- **Confirm syntax for the installed versions.** Search the current docs for the test you're about to
  write — dbt's `data_tests:` key, `dbt_utils.unique_combination_of_columns` args,
  `relationships`/`relationships_where`, source `freshness:` blocks, Elementary anomaly tests. Targets:
  `docs.getdbt.com`, the package's GitHub README, `docs.elementary-data.com`.
- **Prefer the live docs when they disagree with the vignette.** State the delta plainly: "the vignette
  shows X; current docs show Y; using Y." Use `WebFetch` to pull the authoritative page and quote it.

Set up the developer's context so they can implement correctly: the exact `data_tests:` block (dbt 1.8+
uses `data_tests:`, not `tests:`; `data-tests/` dir for singular tests), the package to install, the
config to scope or ramp severity (`where:`, `severity: warn`, `store_failures_as: view`), and a link to
the doc you grounded against.

### 6. Hand back a short coverage summary

Close with a compact table the developer can act on: **model · column / concern · recommended test
(rule code) · package · DAMA dimension · cost class · status (add / already present / N/A with reason)**.
Order by grain-first, then blockers (entity/key integrity) before nice-to-haves (anomaly monitors).

## Guardrails

- **Advise; implement only when asked.** Default to recommending and explaining. Edit a model's
  `.yml`/`.sql` only when the developer explicitly asks, and touch only the lines the test needs.
- **A recommendation can be wrong for this model.** The taxonomy is a vocabulary, not a mandate. Always
  surface the vignette's *When NOT to use* and let the developer decide. Some models are deliberately
  left untested as fixtures — never treat a missing test as automatically a defect.
- **Cite the vignette and the web source.** Every recommendation names the rule code + vignette path it
  came from, and (when implementation is in play) the live doc you grounded the syntax against.
- **Never invent rule codes.** If a need isn't covered by an existing vignette, say so plainly rather
  than fabricating a code — the `references/` catalogue is the only authority for what a rule is.
