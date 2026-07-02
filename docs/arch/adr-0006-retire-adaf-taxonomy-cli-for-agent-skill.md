# Retire the ADAF taxonomy CLI; move LLM taxonomy review to the developer-harness agent skill

**Status:** Accepted
**Date:**   2026-07-02

## Context

[ADR-0005](./adr-0005-adaf-automated-data-assurance-framework.md) consolidated the
testing-taxonomy tooling into one `adaf` CLI: a `catalog.json` single-source-of-truth
(33 rules with dual DQ attribution), deterministic `check taxonomy` detectors, and an
`adaf review` LLM reviewer wired to GitHub Models — the LLM's `rule_code` enum injected
from the catalogue so its outputs could not drift.

Two forces moved us to revisit that decision:

1. **The LLM taxonomy review has too many false positives to gate CI unattended.**
   `adaf review` produces plausible-but-wrong findings on nuanced rules (intent,
   anomaly, semantic-fit judgements). As an unattended, blocking CI gate that FP rate
   is structural — no amount of prompt/threshold tuning makes an LLM judgement over
   subjective rules reliable enough to fail a PR without a human in the loop. Every run
   needed manual adjudication, which erodes trust in the gate and trains reviewers to
   ignore it. The reviewer's *value* is real, but only in a **tight, context-specific
   loop**: a developer (or an agent harness) supplying model context and adjudicating
   findings inline as they work — not a CI loop.

2. **A leaner upstream `adaf` is the shape we want for the CI-grade deterministic half.**
   A sibling repo's `adaf` CLI had matured into a clean, brand-agnostic tool focused on
   the deterministic dbt-CI gates plus the `sdag` lineage/boundary viewer — it never
   carried the catalogue machinery, keeping only the rule-ID *vocabulary* in prose. That
   is exactly the shape the CI-grade tooling should be, and mirroring it keeps us in sync
   with a shared codebase instead of maintaining a bespoke fork.

Meanwhile the `adaf-testing-guide` agent skill already exists and, per its own
**ADR-0001**, is deliberately **reference-driven, not CLI-driven** — it navigates the
taxonomy vignette markdown directly and does not shell out to any binary. That makes it
the natural home for both the taxonomy knowledge and the on-demand LLM review.

## Decision

#### Selected: Retire the taxonomy CLI featureset; re-base `adaf` as a brand-agnostic mirror of the upstream lean CLI; move taxonomy review into the developer-harness agent skill.

On branch `feat/adaf-distill-from-source`:

- **`adaf` becomes a wholesale, brand-agnostic mirror of the upstream lean CLI.** It keeps
  the high-precision, deterministic surface: `sqlfluff`, `deprecations` (dbt-autofix),
  `docscov`/`testcov` coverage, the product-scoped `list`/`defer-state`, the `sdag`
  lineage viewer + boundary-obligation lint (`sdag check`), the `gha` per-product workflow
  generator, and the sticky-comment `report`.
- **Dropped from the CLI:** the `rules` group + `catalog.json` SSoT + its meta-schema, the
  deterministic `check taxonomy` detectors, the `adaf review` LLM command, and the
  taxonomy-markdown `report`. (Archived under `tmp/_archived/`, recoverable from git.)
- **The taxonomy moves entirely into the `adaf-testing-guide` agent skill.** The vignette
  markdown under `plugins/adaf/skills/adaf-testing-guide/references/testing_taxonomy/`
  is now the **canonical source of truth** for the rules and their dual DQ attribution
  (it is version-controlled, readable as GitHub markdown, and actioned through the skill).
  The LLM taxonomy review runs **in the developer's agent harness** — a tight,
  context-rich loop with human-in-the-loop adjudication — not as a CI gate.

## Consequences

- [+] **CI trust restored.** The blocking gates are now only deterministic/high-precision;
  no flaky LLM verdict can fail a PR. Reviewers can believe a red gate again.
- [+] **Less bespoke drift.** `adaf` tracks a shared upstream shape, so improvements flow
  both ways and the CLI is smaller and easier to reason about.
- [+] **The LLM review lives where its false positives are cheap.** In the developer/agent
  harness a wrong finding is dismissed in one turn with full context, instead of blocking a
  merge and demanding a CI re-run.
- [+] **Taxonomy knowledge is self-contained markdown.** No build step, no schema to keep
  in sync with a CLI; it is readable on GitHub and navigable by the skill.
- [-] **No machine-validated SSoT.** With `catalog.json` gone, the vignette headers are the
  source of truth; drift is caught by review and human maintenance, not by
  `adaf rules validate` + a meta-schema.
- [-] **No deterministic `check taxonomy` gate in CI.** The full 33-rule detector set no
  longer runs as a gate; the surviving CI obligations are the coverage gates
  (`docscov`/`testcov`) and the `sdag check` boundary-obligation lint (MD-02/11/12,
  TM-AU-01, MD-07), not the whole taxonomy.
- [-] **No automated PR-comment coverage matrix.** Taxonomy coverage is now a
  developer-initiated skill run rather than a workflow that posts on every PR.
- [-] **Dual-DQ attribution (DAMA-UK6 + Wang–Strong) lives only in the vignette markdown.**

## Options

- **Option 1 (selected)** — Retire the taxonomy CLI, mirror the upstream lean CLI, move
  review into the agent skill.
- **Option 2** — Keep the full ADR-0005 `adaf` and tune the LLM prompt/thresholds to cut
  false positives in CI.
- **Option 3** — Keep `catalog.json` + deterministic `check taxonomy` as CI gates, drop
  only the `adaf review` LLM command.

<details>
<summary>📋 Detailed options outlined</summary>

### Option 2 — Tune the LLM gate rather than remove it

#### Pros
- Preserves the single consolidated tool from ADR-0005.
- Keeps an automated taxonomy signal on every PR.

#### Cons
- The false-positive rate is structural, not a tuning artefact: an LLM judging subjective
  rules (intent/anomaly/semantic-fit) will always misfire often enough that unattended
  blocking gating erodes trust.
- Keeps `adaf` diverging from the shared upstream CLI, with the bespoke catalogue
  maintenance burden.

### Option 3 — Keep the deterministic catalogue, drop only the LLM review

#### Pros
- Removes the flaky gate while retaining a machine-validated SSoT and deterministic
  detectors.

#### Cons
- Partial: retains the `catalog.json` maintenance burden and the dual-scope CLI complexity
  for modest benefit now that the agent skill holds the canonical taxonomy.
- Still forks from the upstream lean CLI we want to track.

</details>
