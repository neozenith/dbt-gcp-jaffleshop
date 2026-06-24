# adaf-testing-guide

Turns "what tests should these models have?" into a concrete, justified test plan. It is a
**reference-driven navigator** over a bundled testing-taxonomy catalogue: it walks a two-question
decision tree to the right *vignette* (a worked test pattern), explains why the test matters and which
package to reach for, then grounds the implementation syntax in current docs via web search. It exists
because picking the right data-quality test — and not over-testing — is a judgement call that a curated
catalogue plus a freshness check makes repeatable.

<details>
<summary>Table of contents</summary>

<!--TOC-->

- [adaf-testing-guide](#adaf-testing-guide)
  - [Quickstart](#quickstart)
  - [Architecture](#architecture)
  - [Reference](#reference)
    - [What it needs](#what-it-needs)
    - [How it operates](#how-it-operates)
    - [Worked example (the output you get)](#worked-example-the-output-you-get)
    - [Troubleshooting](#troubleshooting)
  - [For maintainers](#for-maintainers)

<!--TOC-->

</details>

## Quickstart

Three ways to reach the same guidance.

**In an agent (Claude Code / Copilot / Codex):**

```text
/adaf:adaf-testing-guide which tests should fct_orders and fct_order_items have?
```

**Directly against the catalogue** (no agent needed — the references are plain markdown):

```bash
# 1. Start at the decision tree and framework matrix:
open references/testing_taxonomy/README.md
# 2. Find the vignette for an intent by keyword:
grep -rl "unique_combination_of_columns" references/testing_taxonomy/
```

**Escape hatch — jump straight to a vignette by rule code** when you already know the test:

```bash
# codes: MD-* model · EN-* entity · DM-* dimension · MS-* measure · TM-* time
open references/testing_taxonomy/model/MD-01-grain-test.md      # the grain test
open references/testing_taxonomy/entity/EN-03-foreign-key-integrity.md
```

## Architecture

At a glance — the skill is a pipeline from a model scope to a justified, freshness-checked plan:

```mermaid
flowchart LR
    Q["Scope of<br/>dbt models"]:::sec --> TREE["Decision tree<br/>references/"]:::pri
    TREE --> VIG["Matching vignette<br/>pattern + why"]:::pri
    VIG --> WEB["Web-ground syntax<br/>vs current docs"]:::pri
    WEB --> OUT["Coverage table<br/>test · package · DAMA · cost"]:::sec

    classDef pri fill:#1d4ed8,stroke:#fff,color:#fff,stroke-width:2px
    classDef sec fill:#dbeafe,stroke:#3b82f6,color:#1e293b,stroke-width:1px
```

<details>
<summary>The two-heuristic decision tree (how a column/concern routes to a vignette)</summary>

```mermaid
flowchart TD
    start["What are you<br/>testing?"]:::sec
    q1{"Whole model<br/>or one column?"}:::pri
    q2{"Column's semantic<br/>category in SQL?"}:::pri
    model["model/<br/>grain · contract · freshness"]:::modelN
    entity["entity/<br/>JOIN keys"]:::entN
    dim["dimension/<br/>GROUP BY / WHERE"]:::dimN
    meas["measure/<br/>SUM / COUNT / AVG"]:::measN
    time["time/<br/>date · timestamp"]:::timeN
    vig["Open vignette<br/>by rule code"]:::sec

    start --> q1
    q1 -- "model" --> model
    q1 -- "column" --> q2
    q2 -- "JOIN" --> entity
    q2 -- "GROUP BY" --> dim
    q2 -- "SUM" --> meas
    q2 -- "date" --> time
    model --> vig
    entity --> vig
    dim --> vig
    meas --> vig
    time --> vig

    classDef pri fill:#4338ca,stroke:#fff,color:#fff,stroke-width:2px
    classDef sec fill:#dbeafe,stroke:#3b82f6,color:#1e293b,stroke-width:1px
    classDef modelN fill:#475569,stroke:#fff,color:#fff,stroke-width:2px
    classDef entN fill:#1d4ed8,stroke:#fff,color:#fff,stroke-width:2px
    classDef dimN fill:#6d28d9,stroke:#fff,color:#fff,stroke-width:2px
    classDef measN fill:#047857,stroke:#fff,color:#fff,stroke-width:2px
    classDef timeN fill:#9a3412,stroke:#fff,color:#fff,stroke-width:2px
```

A column can match **more than one** category (a join key that is also a `GROUP BY` axis) — take the
union of the matching suites. The catalogue's root README has the authoritative tree, framework matrix,
and DAMA-UK6 dimension map.

</details>

## Reference

### What it needs

| Requirement | Why |
|-------------|-----|
| The bundled `references/testing_taxonomy/` | The catalogue is the only source of truth for rule codes and patterns. |
| Web access (search + fetch) | Step 5 confirms package/syntax against current docs. **Degrades loudly** if unavailable — it never passes a dated example off as current. |
| A dbt project to inspect | The skill reads each model's `.sql` + `.yml` to reason about real columns and existing tests. |

It runs no warehouse queries, installs nothing, and makes no changes unless you ask it to.

### How it operates

The operating procedure (the six steps: pin grain → walk the tree → index efficiently → explain →
web-ground → summarise) lives in [`SKILL.md`](SKILL.md). This README does not restate it — `SKILL.md`
is the agent's operating manual; read it for the exhaustive flow.

### Worked example (the output you get)

For `fct_order_items`, the skill returns a prioritised plan, grain-first:

| Model | Concern | Test (rule) | Package | DAMA | Cost | Status |
|---|---|---|---|---|---|---|
| `fct_order_items` | grain `(order_id, line_number)` | `unique_combination_of_columns` (MD-01) | dbt-utils | Uniqueness | scan-bound | add |
| `fct_order_items` | `order_id` → orders dim | `relationships` (EN-03) | dbt core | Consistency | cheap | add |
| `fct_order_items` | `quantity` | `accepted_range` ≥ 0 (MS-01) | dbt-utils | Validity | cheap | present |

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Skill recommends a test the model shouldn't have | A vignette's *When NOT to use* was skipped | Quote the negative-space bullets; some models are deliberate fixtures — a missing test is not always a defect. |
| Suggested package/syntax looks stale | Web grounding (step 5) didn't run | Check whether web tools were available; if not, treat the package choice as **unverified** and confirm against `docs.getdbt.com` before merging. |
| A rule code is cited that doesn't exist | Fabricated code | Only codes present in `references/testing_taxonomy/` are valid — there is no external rule catalogue. |
| Skill not found by Copilot/Codex | Tool scans `.agents/skills/`, not plugin dirs | The repo exposes the skill via an `.agents/skills/` symlink; see the [plugin README](../../README.md). |

## For maintainers

Design rationale, the ADR log, and the extension checklist live in [`CLAUDE.md`](CLAUDE.md). Read it
before changing the skill — it records *why* this is reference-driven and freshness-gated rather than a
CLI driver.
