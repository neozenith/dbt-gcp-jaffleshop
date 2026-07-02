# Consolidate testing-taxonomy tooling into ADAF (Automated Data Assurance Framework)

**Status:** Superseded by 0006
**Date:**   2026-06-08

## Context

The project's "testing taxonomy" — the catalogue of data-quality tests a dbt
model *should* carry, and the tooling that checks for them — had grown into
three disconnected pieces that drifted from each other:

1. **A deterministic checker** (`dbt-jaffleshop/cicd_cli/`): a mature argparse
   CLI (`check docs/tests/doc-columns/system-boundaries`, `products
   boundaries`) run as `python -m cicd_cli` off cwd-on-`sys.path` — *not* a
   packaged tool, and living inside the dbt project rather than alongside the
   other repo-level automation.
2. **An LLM reviewer** (`.github/actions/dbt-testing-taxonomy-review/`):
   `review.py` + `rules.json` (33 rules, EN/DM/MS/TM/MD) + an output JSON
   schema, wired to GitHub Models. `rules.json` is the **single source of
   truth**, and the schema's `rule_code` enum is injected from it at runtime so
   the model's allowed outputs cannot drift from the catalogue.
3. **Human documentation** (`docs/guides/testing_taxonomy/`): a README plus 39
   per-rule vignettes.

Three problems motivated this ADR:

- **Scatter.** The same 33-rule taxonomy is referenced by `rules.json`, the
  `review.py` prompt, the deterministic checks, the vignettes, and two
  `CLAUDE.md` maintainer files. Adding or attributing a rule meant touching
  several places, and only the LLM side enforced no-drift.
- **Mis-attribution.** Each rule tagged a `wang_strong` data-quality dimension,
  but the values are actually the **DAMA-UK "six primary dimensions"**
  (Completeness, Uniqueness, Timeliness, Validity, Accuracy, Consistency)
  mislabeled with an academic framework's name. The real Wang–Strong framework
  is a different, four-category model and was never actually applied.
- **Two homes, no developer entry point.** The deterministic CLI ran only in CI
  and the Makefile; the LLM reviewer ran only as a GitHub Action. A developer
  mid-change had no single local tool — and no agent skill — to find and close
  taxonomy gaps before pushing.

The prior art for the fix already exists in this repo: [ADR-0003](./adr-0003-stacks-and-modules-layout.md)
turned an ad-hoc `tf-stack.py` script into `infra/tfs/`, an installable `uv`
tool with a `src/` layout, its own lockfile, and a console-script entry point.
That is the template this ADR ports to the data-assurance side.

## Decision

#### Selected: One `adaf` tool, one rule catalogue, dual DQ attribution, layered suppression, plugin-shaped delivery

Adopt **ADAF — the Automated Data Assurance Framework** — as the single home for
the testing taxonomy. Four decisions, taken together:

### 1. One uvx tool at `.github/cli/adaf/`, absorbing both engines

`adaf` is an installable `uv` tool (the `infra/tfs/` template: `src/` layout,
`[project.scripts] adaf = "adaf.app:main"`, hatchling wheel that bundles the
catalogue as package data, own `uv.lock`). It exposes three command families
over **one** catalogue:

- `adaf rules` — list / show / validate / `explain` the catalogue (the SSoT).
- `adaf check …` — the deterministic gates (migrated from `cicd_cli`), plus a
  new per-rule `check taxonomy` driven by the catalogue's `detection` field.
- `adaf review …` — the LLM reviewer (migrated from `review.py`), with the
  `rule_code` enum still injected from the catalogue at runtime.

The two GitHub Actions and the developer skill all become **thin wrappers** that
call `uvx --from .github/cli/adaf adaf …`. There is exactly one place a rule is
defined, and every consumer derives from it — extending the no-drift invariant
that previously only the LLM schema enjoyed to the deterministic checks and the
skill as well.

### 2. Dual data-quality attribution: DAMA-UK6 primary, Wang–Strong corrected

The catalogue carries **both** frameworks, each correctly attributed:

- `dama` — the DAMA-UK six primary dimensions. The current (mislabeled) values
  move here, which is where they always belonged.
- `wang_strong` — the genuine Wang & Strong (1996) dimensions/categories
  (intrinsic / contextual / representational / accessibility), populated
  correctly for the first time.

DAMA-UK6 is the primary attribution in docs and output because it is the open,
practitioner-standard vocabulary the goal calls for; Wang–Strong is retained as
a correctly-attributed academic cross-reference rather than silently dropped.
This resolves the previously-deferred relabel.

### 3. Layered, lint-style suppression

False positives are managed like a linter: rules can be disabled per-folder and
per-file via an `adaf.yml` config (path-glob → rule codes) **and** per-file /
per-line via inline `-- adaf-disable: CODE (reason)` SQL comments. A reason is
required. Active suppressions are filtered out of the deterministic findings
*and* passed into the LLM review prompt so it won't re-flag them. `adaf rules
explain CODE` and every emitted warning state the exact disable syntax — the
tooling teaches its own escape hatch.

### 4. Plugin-shaped from day one; this repo is the marketplace

The developer-facing capability ships as a **Claude Code plugin** (skill +
the `adaf` CLI it drives), and this repository is its **marketplace**
(`.claude-plugin/marketplace.json`). Building plugin-shaped from the start means
packaging boundaries inform the skill's design rather than being retrofitted.
The skill detects gaps, attributes each to its DAMA-UK6 dimension and vignette,
explains that any finding *may* be a false positive (with the disable syntax),
and — only on request — applies **git-reversible** fixes, never silently
"repairing" the intentionally-broken demo fixture.

## Consequences

- [+] One catalogue is the single source of truth for the deterministic checks,
      the LLM prompt + schema enum, the docs, and the skill — adding/attributing
      a rule is a one-file edit, machine-validated by `adaf rules validate`.
- [+] A developer (or agent) now has one local entry point — `adaf` — that is
      identical to what CI runs, removing the dev/CI behaviour gap.
- [+] Data-quality attribution is finally correct and standards-aligned
      (DAMA-UK6), with Wang–Strong no longer misused.
- [+] False positives have a documented, auditable escape hatch instead of being
      a reason to delete a check.
- [+] The capability is distributable: other dbt projects can install the plugin
      from this marketplace.
- [-] A large one-time migration: file moves out of `dbt-jaffleshop/cicd_cli`
      and `.github/actions/.../review.py`, CI/Makefile rewires, and a doc sweep.
      Mitigated by proving output/exit-code parity before archiving the old
      paths (archive, not delete).
- [-] `adaf` lives at `.github/cli/adaf/` while `tfs` lives at `infra/tfs/` —
      two CLI homes by domain (repo-CI vs. infra). Accepted: each sits next to
      the surface it automates.
- [-] The deterministic-vs-LLM split is now a `detection` field maintainers must
      keep honest per rule; a wrong tag silently routes a rule to the weaker
      checker. Guarded by catalogue validation + the deepeval evaluation suite.

## Options

- One `adaf` tool absorbing both engines, plugin-shaped (**selected**)
- Two tools sharing one catalogue (deterministic CLI + separate LLM action)
- Leave `cicd_cli` in place; only add the shared catalogue + DAMA relabel + skill

<details>
<summary>📋 Detailed options outlined</summary>

### One `adaf` tool absorbing both engines (selected)

#### Pros

- A single SSoT and a single entry point; the no-drift invariant covers every
  consumer. One mental model for contributors.
- The dev skill and both Actions are thin wrappers over the same binary, so they
  cannot diverge in behaviour.

#### Cons

- Largest migration blast radius up front (moves, rewires, doc sweep).

### Two tools sharing one catalogue

#### Pros

- Smaller blast radius; the LLM action keeps its stdlib-only `uv run --no-project`
  simplicity.

#### Cons

- Two entry points and two `CLAUDE.md`s to keep coherent; "consolidation" only
  half-achieved. The catalogue is shared but the *tooling* still scatters.

### Leave `cicd_cli` in place

#### Pros

- Least churn; no CI/Makefile rewire.

#### Cons

- Ignores the explicit "refactor like `tfs`" ask; the CLI stays an unpackaged
  `-m` module inside the dbt project, and the dev/CI homes stay split.

</details>

## References

- [`docs/arch/adr-0003-stacks-and-modules-layout.md`](./adr-0003-stacks-and-modules-layout.md) — the `tfs` uv-tool refactor this ADR ports to the data-assurance side.
- [`docs/guides/testing_taxonomy/`](../guides/testing_taxonomy/) — the rule vignettes (re-attributed to DAMA-UK6 by this change).
- [DAMA-UK, *The Six Primary Dimensions for Data Quality Assessment* (2013)](https://www.dama.org) — the open standard adopted for `dama`.
- Wang, R. & Strong, D. (1996), *Beyond Accuracy: What Data Quality Means to Data Consumers* — the framework now correctly attributed in `wang_strong`.
