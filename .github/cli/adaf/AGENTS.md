# AGENTS.md — `adaf` CLI maintainer guide

**Read the ADR log (below) first.** Each ADR records *why* a decision was made and
ends with a **Lens** — a forward-looking rule to apply to the next related change, so
you can decide without re-litigating the original trade-off. This file is rationale
only; for usage see [README.md](README.md) and [CONTRIBUTING.md](CONTRIBUTING.md), and
never duplicate the command reference here.

<!--TOC-->

- [AGENTS.md — `adaf` CLI maintainer guide](#agentsmd--adaf-cli-maintainer-guide)
  - [What this is (and is not)](#what-this-is-and-is-not)
  - [Development contract](#development-contract)
  - [File map](#file-map)
  - [Architecture principles (invariants a change must preserve)](#architecture-principles-invariants-a-change-must-preserve)
  - [ADR log](#adr-log)
    - [ADR-0001 ✅ — Editable path dependency in the root venv](#adr-0001---editable-path-dependency-in-the-root-venv)
    - [ADR-0002 🔁 — Dependency philosophy: fewest deps, but don't reinvent mature FOSS](#adr-0002---dependency-philosophy-fewest-deps-but-dont-reinvent-mature-foss)
    - [ADR-0003 🔁 — Resolve scope via `dbt ls --selector` (named selectors)](#adr-0003---resolve-scope-via-dbt-ls---selector-named-selectors)
    - [ADR-0004 ⛔ — Check-only; no `--fix` (Superseded by ADR-0008)](#adr-0004---check-only-no---fix-superseded-by-adr-0008)
    - [ADR-0005 ✅ — Derive deprecations failure from `dbt-autofix --json`, not exit code](#adr-0005---derive-deprecations-failure-from-dbt-autofix---json-not-exit-code)
    - [ADR-0006 ✅ — Changed detection = merge-base diff + untracked, glob `models/*.sql`](#adr-0006---changed-detection--merge-base-diff--untracked-glob-modelssql)
    - [ADR-0007 ✅ — Pure-logic unit tests](#adr-0007---pure-logic-unit-tests)
    - [ADR-0008 ✅ — `--fix` opts into code mutation (supersedes ADR-0004)](#adr-0008-----fix-opts-into-code-mutation-supersedes-adr-0004)
    - [ADR-0009 ✅ — Docs and Tests Coverage reads the manifest; it does not shell out](#adr-0009---docs-and-tests-coverage-reads-the-manifest-it-does-not-shell-out)
    - [ADR-0010 🔁 — `sdag` is generate/serve only; skip `state:modified` selectors (ADR-0020 amends)](#adr-0010---sdag-is-generateserve-only-skip-statemodified-selectors-adr-0020-amends)
    - [ADR-0011 ✅ — Grouped sub-packages over a flat layout](#adr-0011---grouped-sub-packages-over-a-flat-layout)
    - [ADR-0012 ✅ — `--selector` is required (supersedes ADR-0003's default)](#adr-0012-----selector-is-required-supersedes-adr-0003s-default)
    - [ADR-0013 ✅ — Process state on a holder, never `global`](#adr-0013---process-state-on-a-holder-never-global)
    - [ADR-0014 ✅ — Centralised dbt helpers in the `dbt/` sub-package](#adr-0014---centralised-dbt-helpers-in-the-dbt-sub-package)
    - [ADR-0015 ✅ — `gha create` round-trips the workflow template per data product](#adr-0015---gha-create-round-trips-the-workflow-template-per-data-product)
    - [ADR-0016 ✅ — CLI ergonomics: aliases, dbt-style boolean flags](#adr-0016---cli-ergonomics-aliases-dbt-style-boolean-flags)
    - [ADR-0017 🔁 — Defer-target manifests from a git ref (worktree-built, sha-cached)](#adr-0017---defer-target-manifests-from-a-git-ref-worktree-built-sha-cached)
    - [ADR-0018 🔁 — sdag selector cache keyed on a freshness fingerprint](#adr-0018---sdag-selector-cache-keyed-on-a-freshness-fingerprint)
    - [ADR-0019 ✅ — Own tooling venv: ruff + strict mypy + pytest via `make ci`](#adr-0019---own-tooling-venv-ruff--strict-mypy--pytest-via-make-ci)
    - [ADR-0020 ✅ — Data-product boundary analysis: classify, cache, lint (amends ADR-0010 & ADR-0018)](#adr-0020---data-product-boundary-analysis-classify-cache-lint-amends-adr-0010--adr-0018)
    - [ADR-0021 ✅ — Defer worktree installs its own packages (supersedes ADR-0017's symlink)](#adr-0021---defer-worktree-installs-its-own-packages-supersedes-adr-0017s-symlink)
    - [ADR-0022 ✅ — One `run_dbt` + one `ManifestView` (extends ADR-0009 & ADR-0014)](#adr-0022---one-run_dbt--one-manifestview-extends-adr-0009--adr-0014)
    - [ADR-0023 ✅ — The `adaf-*` composite actions call the CLI (enabling knobs)](#adr-0023---the-adaf--composite-actions-call-the-cli-enabling-knobs)
    - [ADR-0024 ✅ — `adaf-setup` early-abandons false-positive triggers before the defer build](#adr-0024---adaf-setup-early-abandons-false-positive-triggers-before-the-defer-build)
    - [ADR-0025 ✅ — Collapse `adaf-setup` + `adaf-test` + `adaf-report` into one `adaf-ci` action (supersedes the three-action split in ADR-0023/0024)](#adr-0025---collapse-adaf-setup--adaf-test--adaf-report-into-one-adaf-ci-action-supersedes-the-three-action-split-in-adr-00230024)
    - [ADR-0026 ✅ — Parallel GHA jobs with artifact-shared state (supersedes ADR-0025's single composite job)](#adr-0026---parallel-gha-jobs-with-artifact-shared-state-supersedes-adr-0025s-single-composite-job)
    - [ADR-0027 ✅ — Parallel checks pass the resolved base **sha** as `--base-ref`; dbt args are explicit](#adr-0027---parallel-checks-pass-the-resolved-base-sha-as---base-ref-dbt-args-are-explicit)
    - [ADR-0028 ✅ — Findings JSON + `adaf report` sticky PR comment; run-results artifact seam](#adr-0028---findings-json--adaf-report-sticky-pr-comment-run-results-artifact-seam)
    - [ADR-0029 ✅ — One sticky PR comment, TWO independently-updated sections (decouple findings from the build)](#adr-0029---one-sticky-pr-comment-two-independently-updated-sections-decouple-findings-from-the-build)
    - [ADR-0030 ✅ — `adaf ls --flags`: the selector is a graph ENTRY POINT, the seed is `state:modified ∩ selector`](#adr-0030---adaf-ls---flags-the-selector-is-a-graph-entry-point-the-seed-is-statemodified--selector)
  - [Extension checklist](#extension-checklist)
  - [Known gotchas](#known-gotchas)

<!--TOC-->

## What this is (and is not)

`adaf` is the CLI for the **Automated Data Assurance Framework** — the project's dbt
pull-request quality gates. It re-implements several concerns from the upstream framework,
the first four built on one selection core (changed files that are also in a named selector):

1. `sqlfluff` — SQL lint (`--fix` applies).
2. `deprecations` — dbt-autofix deprecations scan (`--fix` applies).
3. `docscov` — model-description coverage (from the manifest).
4. `testcov` — test coverage (from the manifest).
5. `sdag generate` / `sdag serve` — the data-product lineage viewer; `sdag check` —
   the system-boundary obligation lint (ADR-0020).
6. `gha create <product>` — generate a per-data-product workflow entrypoint.
7. `ls --defer` / `defer-state` — build a cached defer-target manifest from a git ref and show
   which models a selector would build vs defer (the built/deferred subgroup split) (ADR-0017).

It is **not** the full framework — no rules catalogue, taxonomy, LLM review, or reports. The
data-product *boundary* analysis is now in scope (classify + `sdag check`, ADR-0020), but the
heavier upstream pieces are not; if a change starts re-adding those, stop and confirm scope.

## Development contract

Run everything from the **repo root** (never `cd` into the package). The CLI is installed
into the root project's venv as an editable path dep (ADR-0001), so a source edit is live
immediately — no reinstall needed. `--selector` is REQUIRED on the file-scoped gates
(ADR-0012), so verification commands must pass a real selector from `selectors.yml`:

```bash
uv sync --directory dbt-jaffleshop                                       # once: editable-install adaf into the dbt project's venv
uv run --directory dbt-jaffleshop adaf --help                            # smoke the wiring (imports every sub-package)
uv run --directory dbt-jaffleshop adaf list --all --selector demand      # exercises selection + `dbt ls --selector`
uv run --directory dbt-jaffleshop adaf docscov --all --selector demand   # manifest-backed coverage
uv run --directory dbt-jaffleshop adaf sdag generate --no-parse          # viewer over ALL products (writes tmp/sdag/)
uv run --directory dbt-jaffleshop adaf gha create demand --workflows-dir tmp/gha   # workflow generator (write to tmp to dry-run)
```

Before handoff: `make -C .github/cli/adaf ci` (ruff + mypy --strict + pytest) must be green
(ADR-0019), the read-only paths must run clean (exit 0) or report findings (exit 1) — never
raise — and `sdag generate` / `gha create` / defer must write their artifacts. **Do not run
`--fix` to verify** (it rewrites real files; confirm from `--help` + a clean tree).

## File map

Grouped into sub-packages by responsibility, with `app.py` + `config.py` as the top-level
kernel (ADR-0011).

| Path | Role |
|------|------|
| `pyproject.toml` | Package metadata + `adaf` console script; three runtime deps — ruamel.yaml + networkx + elementary-data (ADR-0002). |
| `src/adaf/app.py` | argparse wiring + `main()` dispatch + logging setup only. No business logic. Entry point `adaf.app:main`. |
| `src/adaf/config.py` | Shared kernel: project-root discovery (held on `_state`, not a global — ADR-0013) + path defaults. |
| `src/adaf/git/gitutil.py` | All git: changed-model-file detection (merge-base diff + untracked), sha resolution, worktree lifecycle. |
| `src/adaf/dbt/selection.py` | The scope: changed/all models that are also in `dbt ls --selector` — the core. |
| `src/adaf/dbt/state_modified.py` | Offline `state:modified` calculator: per-resource-type facet ladders + macro closure → the SAME/DIFFERENT verdict. |
| `src/adaf/dbt/selectorflags.py` | Turn a selector into the `--select`/`--state`/`--defer` build flags; the M+ vs hop-operator seed logic (ADR-0030). |
| `src/adaf/dbt/manifest_view.py` | Parse `manifest.json` ONCE; the shared seam every projection builds on (ADR-0022). |
| `src/adaf/dbt/manifest.py` | Coverage projection of the view: model descriptions + test counts (ADR-0009). |
| `src/adaf/dbt/graph.py` | Data-node lineage DAG (a `networkx.DiGraph`) + boundary classification (inbound/outbound/both/inner — ADR-0020). |
| `src/adaf/dbt/runner.py` | `run_dbt` — the one dbt subprocess entry point (`dbt_parse`/`dbt_deps` delegate; ADR-0022). |
| `src/adaf/dbt/selectors.py` | Read named selectors out of selectors.yml (ruamel); shared by sdag + gha (ADR-0014). |
| `src/adaf/dbt/ls.py` | All `dbt ls` invocations: `ls_model_paths` / `ls_member_ids` / `ls_select_paths` (delegates to `run_dbt`). |
| `src/adaf/dbt/cache.py` | sdag freshness + per-selector cache (members + boundary annotation); mtime fingerprint (ADR-0018/0020). |
| `src/adaf/dbt/defer.py` | Build + cache a defer-target manifest from a git ref via a worktree that installs its own deps (ADR-0017/0021). |
| `src/adaf/suppression.py` | `.adaf.yml` per-rule, per-path lint-suppression loader (ADR-0020). |
| `src/adaf/commands/checks.py` | `list`, `deprecations`, `sqlfluff` bodies (shell-outs; `--fix` aware). |
| `src/adaf/commands/coverage.py` | `docscov` + `testcov` bodies (manifest-backed). |
| `src/adaf/commands/defer.py` | `built_model_paths` (the `state:modified+` set `ls --defer` splits on) + `defer-state` (ADR-0017). |
| `src/adaf/commands/sdaglint.py` | `sdag check` body — system-boundary obligation lint with stable rule IDs (ADR-0020). |
| `src/adaf/commands/report.py` | `adaf report` body — aggregate gate findings + the dbt build into one sticky PR comment (ADR-0028/0029). |
| `src/adaf/github.py` | GitHub REST client (stdlib `urllib`) — upsert the sticky PR comment. |
| `src/adaf/sdag/commands.py` | `sdag generate` / `sdag serve` bodies (selectors.yml → viewer; classifies + caches boundaries). |
| `src/adaf/sdag/viewer.py` | The sdag engine: builds Cytoscape JSON, writes multi-file or `--inline`, serves over HTTP. |
| `src/adaf/sdag/assets/` | `sdag.html` + `sdag.js` viewer templates (vendored; resolved relative to `viewer.py`). |
| `src/adaf/gha/commands.py` | `gha create <product>` — round-trips the workflow template into `adaf-<product>.yml`. |

## Architecture principles (invariants a change must preserve)

1. **Lean on the stdlib; reach for mature FOSS, never reinvent.** Imports are stdlib plus three
   small deps — ruamel.yaml + networkx + elementary-data (ADR-0002); the heavy tools (`dbt`, `sqlfluff`,
   `dbt-autofix`) are *subprocesses*, not imports.
2. **Shell out, don't reimplement.** dbt selector grammar, SQL linting, and deprecation
   detection are delegated to their owning tools. (Coverage is the one exception — it
   *reads* the manifest dbt already produced; ADR-0009.)
3. **One scope core for every check.** Each check resolves to the models in `(changed or all)`
   that are ALSO in `dbt ls --selector <name>`, with `--selector` always explicit (ADR-0012) — the
   gates consume the `.sql` paths (`resolve_model_files`), the id-based checks (`sdag check`)
   consume the unique_ids of the same set (`resolve_model_ids`). 
   `sdag generate`/`serve` and `gha` are the only exceptions — they walk all named selectors.
4. **Mutation only behind `--fix`.** The default of every gate is read-only (ADR-0008).
5. **Fail loud.** A non-zero from git/dbt is re-raised, not swallowed.
6. **`app.py` has no logic.** Parsers + dispatch only; bodies live in `commands/`, `sdag/`,
   and `gha/`. No `global` — process state lives on `config._state` (ADR-0013).

## ADR log

Each entry: **Status · Context · Decision · Consequences · Lens.** Ordered ascending.

**Status key (in the heading, so the TOC above summarises it at a glance):**
✅ in-effect · 🔁 amended (still in effect, but evolved by a later ADR) · ⛔ superseded.

### ADR-0001 ✅ — Editable path dependency in the root venv
- **Status**: Accepted.
- **Context**: The checks shell out to `dbt`, `sqlfluff`, `dbt-autofix`. An isolated venv
  wouldn't have those on `PATH`.
- **Decision**: Ship the CLI as a standalone package at `.github/cli/adaf`, consumed by the
  root `pyproject.toml` via `[tool.uv.sources] adaf = { path = ".github/cli/adaf", editable
  = true }` in the `dev` group.
- **Consequences**: `uv run adaf` runs in the venv that already has the tools; source edits
  are live without reinstall.
- **Lens**: When a tool must invoke sibling CLIs, co-locate it in *their* environment rather
  than giving it its own — duplicating a heavy toolchain is the wrong fix.

### ADR-0002 🔁 — Dependency philosophy: fewest deps, but don't reinvent mature FOSS
- **Status**: Accepted (amended: zero-dep → PyYAML → ruamel for sdag/gha → +deepdiff for defer-diff
  → +networkx for the lineage graph → +elementary-data for the `edr` report tool, which forced
  networkx >=3.0 down to >=2.3 → **−deepdiff** when `defer-diff` was folded into `ls --defer`, which
  needs only the modified-path SET, not the field-level reason diff).
- **Context**: The goal is minimal complexity through the fewest dependencies, leaning on the
  stdlib — but NOT at the expense of re-implementing a mature primitive that a well-maintained FOSS
  library already solves off the shelf. Hand-rolling YAML round-tripping, structural diffing, or
  graph algorithms is exactly the wheel-reinvention this principle forbids.
- **Decision**: `dependencies = ["ruamel.yaml>=0.18", "networkx>=2.3", "elementary-data>=0.16"]` and
  nothing else; everything else stays stdlib. Each earns its place by solving a problem the stdlib
  can't, for a feature that needs it: **ruamel.yaml** — comment/order-preserving YAML round-trip
  (selectors.yml + the gha workflow template); **networkx** — the lineage DAG and its traversals
  (don't hand-roll graph algorithms); **elementary-data** — provides the `edr` CLI the `adaf-report`
  composite action shells out to (`edr report`). All three are present transitively in dbt-adjacent
  envs already. (`deepdiff` was dropped when `defer-diff` became `ls --defer`.)
- **Consequences**: Three well-known deps, each tied to one capability; networkx is
  mypy-untyped so it carries a `[[tool.mypy.overrides]] ignore_missing_imports` entry.
  **elementary-data caps `networkx<3`**, so the networkx floor was widened from `>=3.0` to `>=2.3`
  to let both coexist in one venv — adaf touches only the stable core `DiGraph` API (add_*_from,
  nodes/edges, predecessors/successors, has_node), which is identical across 2.x/3.x, so the
  downgrade is behaviour-preserving (255 tests green on networkx 2.8.8). Unlike the other three,
  `edr` is a runtime CLI **not imported by adaf source** — adaf declares it so it flows into the
  root venv (which consumes adaf as an editable path dep), where `uv run edr` resolves.
- **Lens**: Add a dependency only when the stdlib genuinely can't do it AND a feature needs it —
  then prefer a mature FOSS primitive over reinventing one. When a new dep caps a transitive shared
  by an existing one (here networkx), widen your own pin to the intersection only after confirming
  the API surface you use is stable across the range — never hold a stricter pin than the code needs.
  Keep the shell-out gate paths dependency-free.

### ADR-0003 🔁 — Resolve scope via `dbt ls --selector` (named selectors)
- **Status**: Accepted (the *default-selector* part is superseded by ADR-0012).
- **Context**: dbt resolves *named* selectors with `--selector`, honouring the full grammar.
- **Decision**: `--selector NAME` maps to `dbt ls --selector`; the resolved set always
  intersects the scope. (Originally defaulted to `adaf_in_scope`; ADR-0012 removed that.)
- **Consequences**: Full dbt selector grammar is honoured. `state:modified` selectors are
  unusable here (no `--state`) — git provides change detection instead.
- **Lens**: Detect "what changed" with git (cheap, offline); detect "what's in scope" with
  dbt's own selector engine. Never reuse a `state:modified` selector for change detection.

### ADR-0004 ⛔ — Check-only; no `--fix` (Superseded by ADR-0008)
- **Status**: Superseded by ADR-0008.
- **Context**: The request was *initially* explicitly check-only.
- **Decision**: Expose only read-only modes.
- **Consequences**: Safe everywhere; fixing was a separate manual invocation.
- **Lens**: A gate reports; it does not repair — unless a `--fix` flag is explicitly added.

### ADR-0005 ✅ — Derive deprecations failure from `dbt-autofix --json`, not exit code
- **Status**: Accepted.
- **Context**: `dbt-autofix` exits 0 even when it finds deprecated syntax.
- **Decision**: Run `dbt-autofix deprecations -s <dir> -d --json`; any record with a
  `refactors` array is a finding; exit 1 if any. Genuine tool errors (non-zero) re-raise.
- **Consequences**: Findings detected reliably; folder-granularity scan catches sibling `.yml`.
- **Lens**: When a tool's exit code doesn't encode the signal, parse its structured output —
  don't trust exit 0 as "clean".

### ADR-0006 ✅ — Changed detection = merge-base diff + untracked, glob `models/*.sql`
- **Status**: Accepted.
- **Context**: "Changed vs the branch base" must include committed, staged, unstaged, and
  brand-new untracked models.
- **Decision**: `git diff --diff-filter=d $(git merge-base BASE_REF HEAD) -- models/*.sql`
  unioned with `git ls-files --others --exclude-standard -- models/*.sql`.
- **Consequences**: `--relative` paths come back as `models/...`, matching `dbt ls --output
  path` and the manifest's `original_file_path` — no translation.
- **Lens**: Compare against the *merge-base*, not the base tip, so changes already on the
  base don't masquerade as yours. Git pathspec `*` spans directories.

### ADR-0007 ✅ — Pure-logic unit tests
- **Status**: Accepted (resolved — `tests/` now exists, run by `make test`/`ci`).
- **Context**: The first cut shipped without tests; the strict-typing Makefile (ADR-0019)
  needed a meaningful `test` target.
- **Decision**: `tests/` covers the pure logic that needs no warehouse — `dbt/selectors`
  (`_uses_state`, `load_selectors`), `dbt/cache` (freshness + fingerprint invalidation),
  `dbt/manifest` (node extraction + test counts), `dbt/gitutil` (`dirs_of`). Shell-out paths
  (`dbt ls`, `dbt parse`, the viewer) are exercised by manual end-to-end runs, not unit tests.
- **Consequences**: a suite of fast, offline `pytest` tests guards the invalidation chain + parsing
  logic; the subprocess/warehouse paths remain integration-verified.
- **Lens**: Unit-test the pure core (parsing, cache keys, set logic) where it's cheap and
  deterministic; don't mock dbt to "unit test" a shell-out — verify those end-to-end.

### ADR-0008 ✅ — `--fix` opts into code mutation (supersedes ADR-0004)
- **Status**: Accepted.
- **Context**: After the check-only first cut, fix modes were requested for the two gates
  whose tools can repair.
- **Decision**: `--fix` on `sqlfluff` (→ `sqlfluff fix --force`) and `deprecations` (→
  dbt-autofix without `-d`). `--force` skips sqlfluff's prompt so it never hangs on a
  TTY-less stdin. `docscov`/`testcov`/`list`/`sdag`/`gha` have no fix mode.
- **Consequences**: Gates can self-heal opt-in; README warns `--fix` rewrites files.
- **Lens**: Mutation is always opt-in and explicit — a bare invocation must be safe to run
  anywhere. Add `--fix` only to a gate whose underlying tool owns a real fixer.

### ADR-0009 ✅ — Docs and Tests Coverage reads the manifest; it does not shell out
- **Status**: Accepted.
- **Context**: `docscov`/`testcov` need each model's description + test count — facts dbt
  already compiled into `manifest.json`.
- **Decision**: Read `manifest.json` directly (`manifest.py`), joining by
  `original_file_path`; `--parse` refreshes first; a file absent from the manifest fails.
- **Consequences**: Coverage needs no warehouse connection. The sanctioned exception to
  "shell out, don't reimplement" — we read dbt's own artifact, not re-derive it.
- **Lens**: When the fact you need is already in a dbt artifact, read the artifact.

### ADR-0010 🔁 — `sdag` is generate/serve only; skip `state:modified` selectors (ADR-0020 amends)
- **Status**: Amended by ADR-0020 — `sdag` now also classifies boundaries and lints them
  (`sdag check`). The `state:modified`-skip part still holds.
- **Context**: The upstream `products` group also classifies boundaries; this import was
  scoped to generate/serve only. Separately, `state:modified` selectors can't be resolved
  by `dbt ls` without `--state`.
- **Decision**: Port `viewer.py` + the generate/serve handlers only — no boundary analysis.
  `dbt/selectors._uses_state()` detects state-based selectors and the viewer skips them with
  a notice.
- **Consequences**: The viewer renders the static data products and announces what it skipped.
- **Lens**: When a selector can't resolve statically, exclude it with a loud notice — correct
  scoping, not silent degradation. Keep boundary analysis out unless explicitly asked for.

### ADR-0011 ✅ — Grouped sub-packages over a flat layout
- **Status**: Accepted.
- **Context**: The package grew past ~8 modules across distinct concerns; a flat namespace
  obscured the boundaries.
- **Decision**: Group into `dbt/`, `commands/`, `sdag/`, `gha/`; keep `app.py` (entry) and
  `config.py` (kernel) at the top level. Sub-package `__init__` re-exports the handlers so
  `app.py` imports stay shallow.
- **Consequences**: Imports state which layer they cross. Console entry + hatchling
  `packages=["src/adaf"]` unchanged — sub-packages + assets ship automatically.
- **Lens**: Group by concern once a flat package passes ~8 files, but keep the entry point
  and shared kernel at the root. Co-locate vendored assets with the one module that reads them.

### ADR-0012 ✅ — `--selector` is required (supersedes ADR-0003's default)
- **Status**: Accepted (supersedes the default-selector part of ADR-0003).
- **Context**: The original default `adaf_in_scope` was deleted when `selectors.yml` was
  reworked into ~80 real data products — so the default would now fail on every run, and a
  hidden default makes the scope ambiguous anyway.
- **Decision**: `--selector` is `required=True` on every file-scoped gate; no
  `config.DEFAULT_SELECTOR`. A missing selector is an upfront argparse error, not a runtime
  dbt error.
- **Consequences**: Every invocation names its data product — self-documenting and
  intentional. README examples use `--selector <your named selector>`.
- **Lens**: For a flag that selects the *scope* of a wide-reaching operation, prefer
  required-and-explicit over a convenient default; reserve defaults for non-identifying knobs.

### ADR-0013 ✅ — Process state on a holder, never `global`
- **Status**: Accepted.
- **Context**: The discovered project root must be recorded once and read everywhere. The
  `global PROJECT_ROOT` rebind is a forbidden anti-pattern in this repo.
- **Decision**: Hold state on a module-level `_state` dataclass instance; `set_project_root`
  mutates `_state.project_root` (attribute assignment, no name rebind); readers use the
  `config.project_root()` accessor.
- **Consequences**: No `global` keyword; the accessor is a single seam (mockable in tests).
- **Lens**: Mutable module state goes on a holder object you mutate by attribute — never a
  module name you rebind with `global`.

### ADR-0014 ✅ — Centralised dbt helpers in the `dbt/` sub-package
- **Status**: Accepted.
- **Context**: `dbt parse` was duplicated in coverage + sdag, and selector-reading lived in
  sdag where `gha` also needed it.
- **Decision**: `dbt/runner.py` owns the dbt subprocess invocations (`dbt_parse`);
  `dbt/selectors.py` owns reading `selectors.yml`. Both sdag and gha import from there.
- **Consequences**: One place to fix the command form / YAML reading; no cross-feature
  coupling (gha doesn't import sdag).
- **Lens**: When two features shell out to the same tool or read the same file, the helper's
  home is the shared `dbt/` layer — not whichever feature happened to need it first.

### ADR-0015 ✅ — `gha create` round-trips the workflow template per data product
- **Status**: Accepted.
- **Context**: Each data product should opt its slice into CI via its own path-filtered
  workflow that parametrises the shared reusable pieces.
- **Decision**: `gha create <product>` validates the product against `selectors.yml`, then
  ruamel round-trips `adaf-demand.yml` → `adaf-<product>.yml`, swapping only the
  product tokens (`name`, `on.pull_request.paths`, `env.DBT_SELECTOR`, job name). Refuses to
  overwrite without `--force`.
- **Consequences**: Generated workflows keep the template's comments/structure; paths default
  to `models/**/<product>/**` (a convention the author can adjust).
- **Lens**: To template a human-edited config, round-trip it (preserve comments) and swap
  named tokens — don't string-replace, and don't re-serialize from scratch.

### ADR-0016 ✅ — CLI ergonomics: aliases, dbt-style boolean flags
- **Status**: Accepted.
- **Context**: Subcommands wanted short aliases; `sdag` reparsing should default on; flags
  should match dbt conventions.
- **Decision**: argparse `aliases=` (`ls`/`dep`/`fluff`); `sdag --parse` defaults ON with
  `--no-parse` to opt out (argparse `BooleanOptionalAction`, mirroring dbt's `--no-*`); a
  `-v/--debug` flag wires `logging` so `log.info`/`debug` surface.
- **Consequences**: Familiar ergonomics; the viewer reflects the live graph by default.
- **Lens**: Match the ecosystem's flag conventions (dbt's `--no-*`) and let the safe/fresh
  behaviour be the default, with an explicit opt-out for the fast path.

### ADR-0017 🔁 — Defer-target manifests from a git ref (worktree-built, sha-cached)
- **Status**: Amended by ADR-0021 — the worktree now installs its OWN packages (`dbt deps`)
  instead of symlinking the working tree's `dbt_packages`. The sha-keyed worktree+cache holds.
- **Context**: dbt's `--defer` needs a baseline manifest from another ref. Branches move and
  tags can be re-pointed, so "the manifest of `main`/`prod/v5`" must be rebuilt reproducibly
  without disturbing the working tree (ported from the pinned-manifest experiment in `tmp/`).
- **Decision**: `defer.defer_state_dir(ref)` resolves the ref to a commit sha, checks it out
  into a throwaway `git worktree --detach` (with `dbt_packages` symlinked, `DBT_PR_NUMBER=""`),
  runs `dbt parse --target-path`, and caches the manifest at `tmp/adaf_cache/defer/<sha>/`. A
  moving branch re-keys on its new sha (cache miss → rebuild); a fixed sha/tag reuses forever.
  `--defer`/`--defer-ref` on the gates pass `--state <dir> --defer` to `dbt ls`; `ls --defer`
  splits each listing group into built (dbt `state:modified+`) vs deferred sub-sections.
- **Consequences**: Reproducible defer baselines with no working-tree disturbance; the
  worktree is always removed in a `finally`. The first build per sha is slow (a full parse);
  subsequent runs are a cache hit.
- **Lens**: Build "another ref's state" in an isolated worktree keyed on the resolved sha —
  never by stashing/checking out in place, and never keyed on the branch name (which moves).

### ADR-0018 🔁 — sdag selector cache keyed on a freshness fingerprint
- **Status**: Amended by ADR-0020 — the cache is now one file per selector carrying the
  boundary annotation; the freshness-fingerprint keying below is unchanged.
- **Context**: sdag resolves ~80 selectors via one `dbt ls` each — slow to repeat — but a
  stale cache that served wrong membership would be worse than slow.
- **Decision**: `cache.py` keys each selector's member set on a fingerprint of `(manifest
  mtime, selectors.yml mtime)`; a mismatch is a miss (never a stale read). A reparse is run
  only when a source file is newer than the manifest (`manifest_is_fresh`). Cache + parse form
  a one-directional freshness chain: sources → manifest → selector cache.
- **Consequences**: Repeat sdag runs are near-instant; any edit to a model/selectors.yml flips
  the fingerprint and forces a correct re-resolve.
- **Lens**: Make a cache key a *fingerprint of its inputs*, so invalidation is automatic and a
  stale entry can only miss — never trust a manual bust to avoid serving wrong data.

### ADR-0019 ✅ — Own tooling venv: ruff + strict mypy + pytest via `make ci`
- **Status**: Accepted.
- **Context**: The package needed an enforceable quality gate independent of the dbt runtime.
- **Decision**: `.github/cli/adaf/Makefile` runs `ruff` (format+lint), `mypy --strict`, and
  `pytest` in the package's OWN uv venv (the runtime + dev deps) — separate from the
  root venv that carries dbt/sqlfluff. `make ci` = lint + typecheck + test, free + offline.
  The untyped deps (`networkx`/`duckdb`) get a `[[tool.mypy.overrides]] ignore_missing_imports` entry.
- **Consequences**: `make ci` is green and gates handoff; strict typing forced annotations on
  every handler (`args: argparse.Namespace`) — the one sanctioned `Any` is the argparse `sub`.
- **Lens**: Lint/type/test in the package's own venv (no warehouse needed); keep `make ci`
  free + deterministic and run it before every handoff.

### ADR-0020 ✅ — Data-product boundary analysis: classify, cache, lint (amends ADR-0010 & ADR-0018)
- **Status**: Accepted.
- **Context**: A "data product" (a named selector's member set) has a *system boundary*. The
  product owes contracts at its exits and freshness/volume monitoring at its entries — but
  nothing computed that boundary, so the obligations went unchecked.
- **Decision**: `dbt/graph.py` distils the manifest into a **data-node** lineage DAG
  (model/source/seed/snapshot only — test/semantic/exposure edges are dropped) and classifies
  each member as `inbound` / `outbound` / `both` / `inner`, where `inbound` = an external parent
  OR no internal parent (a topological root/source = entry point) and `outbound` = an external
  child OR no internal child (a leaf/final mart = exit point). The graph is held as a
  `networkx.DiGraph` (ADR-0002). `sdag generate` persists each selector's members + boundary
  annotation to its own cache file (`tmp/adaf_cache/selectors/<selector>.json`). `sdag check`
  lints boundary nodes against stable rule IDs drawn from the data-testing taxonomy — `MD-02`
  (contract) / `MD-11` (exposure) / `MD-12` (semantic model) for outbound models, `TM-AU-01`
  (source freshness) and `MD-07` (volume anomaly) for inbound nodes — with `.adaf.yml` per-rule,
  per-path suppression (`suppression.py`).
- **Consequences**: The boundary is inspectable per selector and enforced as a gate; sources
  now classify as inbound, so `TM-AU-01` (source freshness) is reachable (it was dead under an
  external-parent-only definition). Volume-anomaly detection is a documented heuristic.
- **Lens**: Filter the lineage to *data* nodes before reasoning about a product's boundary —
  attachments (tests, semantic models) are not lineage and would mislabel every tested model
  as an exit. A boundary rule that can never fire is a bug, not a passing check.

### ADR-0021 ✅ — Defer worktree installs its own packages (supersedes ADR-0017's symlink)
- **Status**: Accepted (supersedes the `dbt_packages`-symlink part of ADR-0017).
- **Context**: ADR-0017 symlinked the working tree's `dbt_packages` into the defer worktree.
  But `packages.yml` / `package-lock.yml` can differ between commits, so the symlink could
  bind the wrong dependency graph into a past ref's parse — silently distorting the defer target.
- **Decision**: The worktree runs its OWN `dbt deps` (`runner.dbt_deps(project_dir=wt)`) before
  the parse; nothing from the working tree's `dbt_packages` is symlinked in.
- **Consequences**: The defer-target manifest reflects exactly the packages that ref declared,
  at the cost of a `dbt deps` per cache miss. Git lifecycle lives in `git/gitutil.py`.
- **Lens**: When reconstructing a past ref's build, install *that ref's* dependencies — never
  borrow the current tree's, even when it seems faster.

### ADR-0022 ✅ — One `run_dbt` + one `ManifestView` (extends ADR-0009 & ADR-0014)
- **Status**: Accepted.
- **Context**: dbt's `manifest.json` was parsed and walked in four places (coverage, lineage
  graph, lint artifacts, the viewer), and the dbt subprocess+fail-loud wrapper existed twice
  (`runner` and `ls`). Both are shallow duplication of a central artifact / a central action.
- **Decision**: `dbt/runner.run_dbt` is the single dbt subprocess entry point — `dbt_parse`,
  `dbt_deps`, and `ls.py` all delegate to it. `dbt/manifest_view.ManifestView` parses the
  manifest ONCE and owns the mechanical layer (section iteration, `parent_map`→edges with a
  `depends_on` fallback, finding test nodes); the coverage `Manifest`, lineage `Graph`, and lint
  `Artifacts` each build via a `from_view(view)` projection (their `load`/`from_dict`/
  `from_manifest` entry points stay as thin wrappers).
- **Consequences**: A dbt manifest-schema change is a one-file edit; a single `sdag generate`
  parses the manifest once for both the viewer and boundary classification. The view is the
  seam the projections are unit-tested through.
- **Lens**: When several modules re-read the same artifact or repeat the same shell-out, the
  shared seam owns the *mechanism*; each caller keeps its *meaning* via a thin projection.

### ADR-0023 ✅ — The `adaf-*` composite actions call the CLI (enabling knobs)
- **Status**: Accepted (the CLI-calling decision holds; the three-file split is superseded by ADR-0025, which merges the actions into one `adaf-ci`).
- **Context**: `.github/actions/adaf-setup`/`adaf-test` reimplemented in shell what the CLI now
  covers: base-ref state, modified-file resolution, and SQLFluff lint. A faithful swap needed a
  few knobs the CLI lacked, so a naive swap would have changed CI behaviour.
- **Decision**: Add `--target` (the live `dbt ls` target) and `--defer-target` (the target the
  defer-target manifest is parsed under, when it differs — e.g. `--target dev --defer-target
  nonprod`; absent it falls back to `--target`; the defer cache keys on `(sha, defer-target)`);
  `--format` on `sqlfluff` (passes SQLFluff's `--format github-annotation-native` for inline PR
  annotations); and an `adaf defer-state` command that builds/reuses the defer state and prints
  its `--state` dir. The reusable actions take the named **`selector` as an input** fed from the
  per-product `adaf-<product>.yml` workflow (never a hardcoded selector). `adaf-setup` resolves the
  base ref to a sha once, then runs `list` (changed-only ∩ selector) as an early abandon gate and
  builds `defer-state` only when that gate finds in-scope changes (ADR-0024) — together replacing
  `fetch-state.sh` + `get-modified.sh`; `adaf-test` lints via `adaf sqlfluff --format …`. The
  `adaf-report` (EDR) and `adaf-cleanup` (bq) actions stay — no CLI equivalent (out of scope).
- **Consequences**: At most one `defer-state` build per job (skipped on a no-op trigger, ADR-0024)
  is reused by `sqlfluff` + the other deferred checks (shared sha cache). Verified locally by `make
  ci` only — `actionlint`/`shellcheck` weren't installed, so the workflow itself ships unverified
  against real GitHub Actions until the next PR exercises it.
- **Lens**: Before swapping a CI shell step for a CLI call, enumerate the *exact* behaviour
  (output format, target, artifact paths); if the CLI can't reproduce it, add the knob first —
  never let a "modernise CI" change silently drop a behaviour like inline annotations.

### ADR-0024 ✅ — `adaf-setup` early-abandons false-positive triggers before the defer build
- **Status**: Accepted (the gate logic holds; `adaf-setup` is now Phase 1 of the merged `adaf-ci` action — ADR-0025).
- **Context**: Per-product workflows path-trigger on `models/**` + `dbt_project.yml`, so a
  `dbt_project.yml` edit — or a model change in a *different* product — fires every product's
  workflow. The old `adaf-setup` built the expensive `defer-state` (isolated worktree + its own
  `dbt parse`) and only then ran `list --all`, which returns the whole selector regardless of the
  diff. `has-modified` was therefore effectively always true and no run ever abandoned.
- **Decision**: Move the `list` detection ahead of `defer-state` and resolve it as the default
  changed-only scope: `adaf list --selector <s> --base-ref <sha>` = git-modified files ∩ the
  product's canonical selector (no `--defer` — the intersection needs only the parsed manifest and
  the git diff, not a baseline). Empty ⇒ `has-modified=false`, and both `defer-state` and
  `resolve-options` are gated off, so the job abandons before the costly build; `adaf-test`'s checks
  already gate on `has-modified`. Checkout gains `fetch-depth: 0` so the `merge-base` diff resolves.
- **Consequences**: A `dbt_project.yml`-only PR (or one touching another product) skips the defer
  build and every check — the common false-positive trigger costs a `dbt parse`, not a full run.
  Trade-off: a config-only change that affects compilation but touches no in-scope `.sql` is also
  skipped; a product that needs config changes to force a full run flips the gate back to `--all`.
- **Lens**: When a CI gate must mean "did MY scope change", resolve it as changed-only ∩ selector
  and run it before any expensive setup — a whole-selector (`--all`) probe can't detect change and
  silently defeats the gate.

### ADR-0025 ✅ — Collapse `adaf-setup` + `adaf-test` + `adaf-report` into one `adaf-ci` action (supersedes the three-action split in ADR-0023/0024)
- **Status**: Accepted (the single-job composite is superseded by ADR-0026, which splits the pipeline into parallel jobs; the `has-modified`/`!cancelled()` report-gating reasoning below still holds, now at job level).
- **Context**: The three composite actions were always called as a fixed sequence — the workflow
  ran `adaf-test` (which internally `uses: ./.github/actions/adaf-setup`) then a separate
  `if: always()` `adaf-report` step. The split spread one linear pipeline across three `action.yml`
  files plus cross-action `outputs`/`steps.*.outputs` plumbing, so reading or changing the flow meant
  hopping files, and the per-action input lists drifted (setup/test both re-declared `target`,
  `selector`, `defer-target`). Nothing else consumed the actions independently.
- **Decision**: Merge all steps into a single `adaf-ci/action.yml` with three commented phases
  (Setup / Test / Report). Cross-action output refs collapse to in-file `steps.base.outputs.sha` +
  `steps.modified-files.outputs.has-modified`. The old workflow-level `if: always()` on the report
  step becomes per-step `if: ${{ steps.modified-files.outputs.has-modified == 'true' && !cancelled() }}`
  inside Phase 3 — `!cancelled()` keeps the report running on a **red** build, while the `has-modified`
  guard makes the early-abandon gate skip the report too (a false-positive trigger reports nothing).
  Bundled helpers (`resolve-options.sh`, `report_dbt_summary.py`, `utils.py`,
  `summary_template.md`) move beside the action and are referenced via `$GITHUB_ACTION_PATH` (run
  with `bash` — `gha init`'s `write_text` deploy drops the exec bit). `adaf-cleanup` stays separate.
- **Consequences**: One file to read/version; `gha init` deploys two action dirs (`adaf-ci`,
  `adaf-cleanup`) not four. The asset packaging is glob-based (`rglob`), so no manifest change was
  needed and the name-agnostic `test_gha_init` suite still passes. Trade-off: the three phases can no
  longer be invoked à la carte — acceptable, since they never were. The workflow **job id** stays
  `adaf-test` (what `gha create` patches in `commands.py`); only the action collapsed.
- **Lens**: Collapse multiple composite actions into one only when they form a single fixed sequence
  with no independent consumer — and when you do, push each cross-action `output` down to an in-file
  `steps.*.outputs` ref. For an `if: always()` wrapper, split its two intents: `!cancelled()` keeps a
  step running through a *failed* peer, while a domain guard (here `has-modified`) decides whether the
  step should run at all. A bare `always()`/`!cancelled()` conflates "report on failure" with "report
  even when nothing was in scope" — gate the latter on the same change signal as the rest of the pipeline.

### ADR-0026 ✅ — Parallel GHA jobs with artifact-shared state (supersedes ADR-0025's single composite job)
- **Status**: Accepted.
- **Context**: The single `adaf-ci` composite ran the whole pipeline in one job, so the five checks
  and `dbt compile`/`build` were strictly sequential — wall-clock = the sum of every gate, and one
  check's runtime blocked the next. The user wanted each check (sqlfluff, deprecations, docscov,
  testcov, sdag-check) and the dbt build as **independent parallel jobs**, each its own
  branch-protection status check. Composite actions are single-job, so this can't live in an action —
  it must be a multi-job workflow. The hard part: jobs run on separate runners with no shared
  filesystem, but every check needs the parsed manifest and the `defer-state` baseline.
- **Decision**: Rewrite the per-product workflow as a job graph — `setup` → (`checks` matrix ∥
  `dbt-build`) → `report`. `setup` parses + gates + builds defer-state **once** and uploads
  `adaf-manifest` (`target/`) + `adaf-defer-state` (`tmp/adaf_cache/defer/`); it exposes `has-modified`
  + `base-sha` as **job outputs**. Downstream jobs restore those artifacts (so `adaf --defer-ref <sha>`
  hits the sha-keyed cache — no rebuild) via a slimmed `adaf-ci` composite that is now just the
  **per-job bootstrap** (auth + uv/dbt env + optional artifact restore). The five checks are one
  `strategy.matrix` over `cmd` (the leg name AND the adaf subcommand, enriched via `include`); each
  leg's run step is gated by `if: ${{ env[matrix.toggle] == 'true' }}` (the `env` context indexed by
  the matrix value — no shell toggle logic) and `continue-on-error` is `true` only for `sqlfluff`. `dbt-build` uploads
  `adaf-run-results`; `report` (`needs: [checks, dbt-build]`, `if: has-modified && !cancelled()`)
  restores it. `gha create` now fills `__PRODUCT__` across **all** job `name`s (the old single
  `adaf-test` job key is gone — see `commands.py`).
- **Consequences**: Checks run concurrently (wall-clock ≈ slowest gate, not the sum); each is a
  distinct required status check. Cost: the env bootstrap (uv sync + dbt deps) repeats per job, and
  the defer-state/manifest cross the wire as artifacts. `dbt-build` passes the restored defer cache
  path `tmp/adaf_cache/defer/<base-sha>/<target>` straight to `dbt --state … --defer` (explicit args,
  no `resolve-options.sh`/`DBT_ARGS`/`mapfile` indirection — see ADR-0027). Checkout stays a per-job
  step (a local `uses:` needs the repo present before the action resolves), so it is NOT in the
  bootstrap action.
- **Lens**: When parallelising a CI pipeline whose stages share expensive derived state, compute that
  state **once** in a gate job, publish it as artifacts + job outputs, and have each parallel job
  restore it into the exact cache path the tool expects — so the tool's own cache-hit logic skips the
  rebuild. Duplicating cheap setup (env) per job is fine; duplicating the expensive derivation is the
  thing artifacts exist to prevent.

### ADR-0027 ✅ — Parallel checks pass the resolved base **sha** as `--base-ref`; dbt args are explicit
- **Status**: Accepted.
- **Context**: Two issues surfaced on the first real PR run of the parallel workflow. (1) Every
  `checks` leg failed with `git merge-base main HEAD failed (exit 128): fatal: Not a valid object
  name main`. `_add_scope` defaults `--base-ref` to `main` and changed-only detection runs
  `git merge-base <base-ref> HEAD`; a `pull_request` checkout has no local `main` ref (only the
  fetched commit), so the diff blew up. The single-job design never hit this because its checks ran
  `--all` (whole-selector scope, no merge-base). (2) `dbt-build` composed args through
  `resolve-options.sh` → a newline-joined `DBT_ARGS` env → `mapfile -t args` → `dbt "${args[@]}"`,
  which hid the actual selector/state/defer flags behind three layers of indirection.
- **Decision**: (1) Pass `--base-ref "${{ needs.setup.outputs.base-sha }}"` to every check — the
  same sha already used for `--defer-ref` (so changed-detection and the defer cache agree, and the
  sha is a real object under `fetch-depth: 0`). (2) Drop `resolve-options.sh`/`DBT_ARGS`/`mapfile`;
  `dbt-build` now calls `dbt compile`/`build --target … --selector … --state
  tmp/adaf_cache/defer/<base-sha>/<target> --defer` inline. `resolve-options.sh` is deleted from the
  bundled assets.
- **Consequences**: Checks default to **changed-only** scope (not `--all`) and resolve it against the
  PR base sha. The dbt invocation is readable at a glance and derives entirely from values already in
  hand (target, selector, base-sha). One fewer bundled asset. Edge case left open: if `main` advances
  mid-run so the base sha is no longer reachable from the PR merge ref, the sha object could be
  absent — not observed (concurrency `cancel-in-progress` makes it unlikely); revisit with an explicit
  `git fetch origin <sha>` if it ever bites.
- **Lens**: In CI, never let a tool fall back to a *branch name* for git operations — a PR checkout
  has commits, not refs. Resolve the base to a sha once (in the gate job), thread that sha through
  every consumer, and prefer explicit command flags over env-var/array indirection so a failed run
  shows the real arguments in the log.

### ADR-0028 ✅ — Findings JSON + `adaf report` sticky PR comment; run-results artifact seam
- **Status**: Accepted.
- **Context**: The checks only emitted human ANSI text; CI couldn't aggregate them. Each push posted a
  fresh dbt-summary (the standalone `report_dbt_summary.py` GHA-asset script appended to the step
  summary), so a 30-commit PR had no single evolving status. We wanted machine-readable findings per
  check, uploaded as artifacts, and one **sticky** PR comment summarising them + the dbt build.
- **Decision**: (1) A shared `--json-out PATH` (in `_add_scope`) writes a `{check, exit_code,
  findings:[Finding.to_dict()]}` JSON via a single `report.emit_findings()` exit point on every check;
  the existing `-q` suppresses the human text so `--json-out -q` is the json-only mode. (2) A new
  `adaf report` subcommand aggregates the findings JSONs + the dbt build into one markdown body and
  upserts a marker-stamped PR comment via a stdlib-`urllib` GitHub client (`adaf.github`, no HTTP dep —
  ADR-0002), find-by-`<!-- adaf-report -->` then PATCH-or-POST. (3) `report_dbt_summary`/`utils`/
  `report_dbt_annotations`/`summary_template` are **deleted** from the bundled assets — folded into
  `adaf.commands.report` + a new **run-results artifact seam** `adaf.dbt.runresults` that mirrors
  `adaf.dbt.artifact` (JSON reader + a Fusion-parquet reader sharing `read_parquet_rows`) and reuses
  `ManifestView` for node name/path (no re-projection). (4) The multiversion harness now also `dbt
  build`s + `docs generate`s and records the manifest/run_results/catalog artifact KIND + a full
  `target/metadata` listing per engine. That probe **captured the real Fusion layout** —
  `metadata/run/results/v1_0.parquet` (results, joined to `run/invocations` for elapsed/generated_at)
  and `metadata/catalog/columns/v1_0.parquet` — which is what `ParquetRunResultsArtifact` now reads
  (verified by a synthesised-fixture unit test); the listing still catches any future new artifact.
- **Consequences**: `adaf-ci` is now just the bootstrap `action.yml` (helpers gone). The `report` job
  gains `pull-requests: write`. `GITHUB_API_URL` is honoured (Actions sets it; also the test seam, so
  the github client is tested against a real local `http.server`, no mocks). `load_run_results` on a
  *directory* prefers parquet (mirrors `load_artifact`); the workflow passes the `run_results.json`
  *file* so dbt-core CI stays JSON. **Catalog** parquet is captured by the probe but has no adaf reader
  — nothing consumes a catalog yet, so a reader would be dead code (add one with its first consumer).
- **Lens**: Give every gate a machine-readable artifact behind a `--json-out` flag routed through ONE
  emit function, and aggregate downstream rather than teaching each gate to post. For a new artifact
  format you can't yet verify, wire the *seam* (detection + a loud stub) and a probe that captures it —
  never ship a reader for a guessed schema.

### ADR-0029 ✅ — One sticky PR comment, TWO independently-updated sections (decouple findings from the build)
- **Status**: Accepted (amends ADR-0028's single-body comment).
- **Context**: ADR-0028 had the `report` job `needs: [setup, checks, dbt-build]` and render the whole
  comment in one `adaf report` call — so the findings summary was hostage to the **slow** dbt build,
  appearing minutes late even though the gates finished early. We wanted the findings to post the moment
  the checks finish, while the build/EDR summary fills in later, **in the same comment**.
- **Decision**: The comment body carries two marker-delimited sections — `<!-- adaf:findings -->…` and
  `<!-- adaf:build -->…` — created from a skeleton with both as "pending" placeholders.
  `adaf report --section findings|build` renders + **splices ONLY its section** via
  `github.upsert_section` (regex replace between the section markers), never clobbering the other; the
  first job to run creates the comment. The `report` job now `needs: [setup, checks]` (posts findings
  fast); the `dbt-build` job posts the `build` section (run-results table + EDR + sdag artifact links)
  after it builds. `--section all` renders the whole comment (for `--dry-run`/local). Findings detail is
  ONE collapsible `<details>` **per check that has findings** (none when all clean).
- **Consequences**: Two jobs hold `pull-requests: write` and write the same comment concurrently; the
  splice is section-scoped so they don't race destructively, and every push re-runs both → converges.
  An older single-body comment is rebuilt from the skeleton (the section markers are absent) rather than
  silently no-op'd. The findings comment no longer waits on the build — the whole point.
- **Lens**: When one sticky surface aggregates outputs from jobs of very different latency, give each
  job its own marker-delimited **section** and a splice-don't-replace upsert — so the fast producer is
  never gated on the slow one, and neither overwrites the other.

### ADR-0030 ✅ — `adaf ls --flags`: the selector is a graph ENTRY POINT, the seed is `state:modified ∩ selector`
- **Status**: Accepted.
- **Context**: The `dbt-build` job ran `dbt build --selector demand --state … --defer`, which builds the
  WHOLE product every PR (deferring unchanged *refs*, but still building every selected model). We want
  it to build only what the PR changed **plus the downstream it invalidates** — the standard PR pattern.
  `state:modified` expresses "changed", but the naive `state:modified,demand` (intersection) can't be
  expanded: dbt's `+`/`@` operators attach to an *atom*, never to the *result* of an intersection, so
  `state:modified,demand+` means "modified ∩ (demand+descendants)" — it builds only the changed
  model, never its dependents.
- **Decision**: `adaf ls --flags` treats the selector as an **entry point** and RESOLVES the seed itself
  rather than emitting a textual selector. With `--defer` the seed = `state:modified ∩ selector`, computed
  by intersecting two `dbt ls` resolutions (`--selector <name>` and `--select state:modified`, both vs the
  defer-state baseline) — so the full selector grammar is dbt's job, not ours. `--upstream N`/`--downstream
  N` then attach `N+`/`+N` (bare ⇒ `+`) to each **concrete seed path**, which dbt *can* traverse — across
  product boundaries (a non-product model downstream of a changed product model builds; an unrelated
  changed model does not). It emits `--select <path>+ … --state <defer-dir> --defer`; an empty seed emits
  `""` and the job skips the build. The pure composition (`apply_operators`/`format_flags`/`build`) is
  unit-tested exhaustively; `compose` owns the `dbt ls` shell-out.
- **Consequences**: `dbt-build` runs a `Resolve dbt build flags` step then `dbt build --target … $flags`.
  Verified on a real PR: `state:modified ∩ demand` resolved to exactly the one changed demand model. The
  **non-defer** path (whole-selector seed) emits paths too; whether to instead emit a *textual* `tag:`
  unpack there (and how to handle selector definitions that don't decompose to flat `--select`/`--exclude`)
  is a deliberately-deferred follow-up — it doesn't block the defer path the build uses.
- **Lens**: When a tool's set algebra can't express "operate on the *result* of a set operation" (dbt
  operators bind to atoms, not intersections), resolve the set to concrete members yourself and emit those
  with the operators attached — don't contort the textual expression into something that silently selects
  the wrong nodes.

## Extension checklist

- [ ] New behaviour stays within scope (the seven concerns); else confirm with the user.
- [ ] Logic lives in `commands/`/`sdag/`/`gha/`/`dbt/`; `app.py` only wires it.
- [ ] Runtime deps stay minimal (ruamel + networkx + elementary-data — ADR-0002), mature-FOSS over reinvention; mutation only behind `--fix` (ADR-0008).
- [ ] `--selector` stays required on file-scoped gates (ADR-0012); no `global` (ADR-0013).
- [ ] Shell-outs fail loud (re-raise non-zero); empty scope returns 0, not error.
- [ ] Read-only paths verified from repo root with a real `--selector`; `--fix` NOT executed.
- [ ] README + CONTRIBUTING updated; diagrams re-pass the mermaid gates; TOC regenerated.

## Known gotchas

| Symptom | Cause / fix |
|---------|-------------|
| `sqlfluff` fails with `'NoneType' … close` or auth errors | The `.sqlfluff` dbt templater opens a BigQuery connection — needs GCP ADC (`gcloud auth application-default login`). `dbt ls`/`dbt-autofix`/coverage only parse. |
| `error: the following arguments are required: --selector` | By design (ADR-0012) — pass an explicit named selector from `selectors.yml`. |
| `dbt ls --selector … not found` | The named selector must exist in `selectors.yml` (there is no default). |
| `git merge-base` fails in CI | Fetch the base ref first — `actions/checkout` with `fetch-depth: 0` (or `git fetch origin <base>`). |
| `docscov`/`testcov` report "not in manifest" | Stale/missing `manifest.json` — pass `--parse`. Coverage reads the manifest, never the warehouse (ADR-0009). |
| `sdag generate` is slow | It resolves *every* static selector via one `dbt ls` each (~80) — that's by design (no `--product` filter). `--no-parse` skips the upfront parse; a faster bulk resolve is a future optimisation. |
| sdag page blank when opened as a file | `file://` blocks the JSON `fetch` — use `adaf sdag serve`, or `--inline` for a standalone HTML that needs no fetch. |
| `sdag serve` says "port in use" | Pass `--port <n>`; the server binds `127.0.0.1` and won't clobber an existing listener. |
| `adaf: command not found` | Run `uv sync` first; it editable-installs the package into the root venv. |
| Viewer colours a `test` (or other non-data node) as an outbound boundary when a selector filter is active | Boundary classification is **duplicated**: `adaf.dbt.graph.Graph` (server-side, used by `sdag check` + the cache) and `applyFilter()` in `sdag/assets/sdag.js` (client-side, the filtered-view colouring). Both MUST restrict to the data-node backbone (`DATA_RESOURCE_TYPES` = model/source/seed/snapshot) in BOTH the member set and the neighbour sets — a childless `test` otherwise reads as an outbound leaf. Keep the JS `DATA_RESOURCE_TYPES` set in sync with the Python one whenever either changes. |
