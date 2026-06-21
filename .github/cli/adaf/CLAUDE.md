# Maintaining & extending `adaf`

Guidance for anyone (human or agent) changing this tool. Read `README.md` first
for what it does; this file is rationale and invariants only.

> **Status:** in place: the `rules` group + catalogue (SSoT); the `check`/`products` groups;
> the `review` group (GitHub Models, `rule_code` enum injected from the catalogue); the
> deterministic taxonomy detectors (`check taxonomy`) + suppression layer — per
> [ADR-0005](../../../docs/arch/adr-0005-adaf-automated-data-assurance-framework.md).
>
> **Backported from the sibling `dbt_cartology_cdip/.github/cli/adaf` (the dbt-engineering
> specialist):** the `run_dbt`/`ManifestView`/artifact seam (parse the manifest once; `[fusion]`
> parquet reader for dbt v2.0); the **`defer-diff`/`defer-state`** workflow commands (built-vs-deferred
> split via a cached worktree-parsed baseline + deepdiff); the **`list`/`ls`** scope preview
> (hop-walks, `--macros`, `--paths`, `--commands` on the gates); the **`gha`** workflow generator
> (paths derived from `dbt ls`, three glob algorithms + false-positive audit); the **`sdag check`**
> boundary-obligation lint (catalogue rule IDs MD-02/11/12, TM-AU-01, MD-07); the **selector cache**
> (fingerprint-keyed, parallel resolution) + **viewer enrichment** (compliance RAG rings, governance,
> inline/archive); and the **`tests/multiversion/`** Docker matrix (dbt 1.11/1.12/2.0, off `make ci`).
> These ride on a SECOND, product-scoped selection (`dbt/scope.py`, required `--selector` + hop-walks),
> parallel to the catalogue checks' changed/all + `--select`/`--exclude` (`dbt/selection.py`) — the two
> coexist by design; a workflow command is product-scoped, a `check` gate is changed-file-scoped.

## The one idea that holds it together: the catalogue is the only source of truth

`src/adaf/rules/catalog.json` defines every rule **once**. Everything else is
derived from it at runtime:

| Consumer | Derives |
|----------|---------|
| `adaf rules` | the catalogue, read/validated directly |
| `adaf check taxonomy` | the per-rule deterministic detectors keyed by `detection` |
| `adaf review` | the LLM prompt catalogue **and** the output schema's `rule_code` enum (injected at call time) |
| docs vignettes | pointed to by each rule's `doc` |
| the dev skill | finding → DAMA dimension + vignette |

**Never** maintain the rule list, the schema enum, or the DQ-dimension tags in a
second place. Add a rule by editing `catalog.json` only; `adaf rules validate`
(and `tests/test_rules.py`) is the guard.

## Module map

```
.github/cli/adaf/
├── Makefile                # dev command-and-control: fix (inner loop) · ci (lint+typecheck+test+validate)
├── pyproject.toml          # [project.scripts] adaf = adaf.app:main; hatchling bundles rules/ + assets/
├── src/adaf/
│   ├── app.py              # argparse wiring + main(). NO business logic. Lazy project discovery.
│   ├── __main__.py         # `python -m adaf` entry
│   ├── config.py           # PROJECT_ROOT discovery (dbt_project.yml walk-up), default paths, project_root()
│   ├── gitutil.py          # changed-file detection + git WORKTREE lifecycle (resolve_sha/add/remove)
│   ├── graph.py            # data-node lineage DAG + classify_boundary() / Graph.classify() — pure
│   ├── report.py           # shared colourised Finding/headline/table substrate (list, defer-diff, gha, sdaglint)
│   ├── annotations.py      # per-product compliance rollup (reuses sdaglint RULES) → enriches the selector cache
│   ├── dbt/                # dbt primitives, grouped: thin readers/resolvers over dbt's artifacts
│   │   ├── runner.py       #   THE single dbt subprocess seam: run_dbt / dbt_parse / dbt_deps
│   │   ├── ls.py           #   THE single `dbt ls` home: select/exclude + named-selector paths/member-ids
│   │   ├── manifest_view.py#   ManifestView — parse manifest.json ONCE; every projection builds from_view
│   │   ├── artifact.py     #   JsonManifestArtifact + ParquetManifestArtifact (dbt v2.0 Fusion; [fusion] extra)
│   │   ├── manifest.py     #   manifest.json → ModelDoc (description, declared columns, test_count)
│   │   ├── catalog.py      #   catalog.json → RESOLVED warehouse columns per model
│   │   ├── selectors.py    #   selectors.yml → named selectors (+ state: detection) for the viewer/gha
│   │   ├── cache.py        #   fingerprint-keyed per-selector membership+boundary cache (sdag viewer)
│   │   ├── defer.py        #   defer_state_dir — worktree-parse a git ref's manifest, cache per (sha,target)
│   │   ├── selection.py    #   CHECK-gate scope: --changed-only/--all/--select/--exclude → list[Path]
│   │   └── scope.py        #   PRODUCT scope: required --selector + --upstream/--downstream/--defer (list, defer, sdag check)
│   ├── taxonomy.py         # NodeFacts + the deterministic detectors (DETECTORS registry)
│   ├── suppression.py      # adaf.yml + inline `-- adaf-disable` parsing
│   ├── viewer.py + assets/ # sdag Cytoscape viewer (governance + compliance RAG + inline/archive + design-tokens)
│   ├── gha/                # `adaf gha create/update/analyse` — per-product workflow generator + glob collapse
│   ├── utils/              # cross-cutting infra, grouped: logging_setup · formatting · style · toollog
│   ├── reports/            # the result DATACLASSES, grouped (one module per domain). Render-only.
│   ├── rules/              # the SSoT: catalog.json + catalog.schema.json + review-output.schema.json + loader
│   └── commands/           # evaluation logic + handlers (NO report dataclasses — those live in reports/)
│       ├── rules.py        # `adaf rules list/show/validate/explain`
│       ├── coverage.py     # check docs / tests / doc-columns
│       ├── deprecations.py # check deprecations (dbt-autofix); --commands prints the argv
│       ├── sqlfluff.py     # check lint / format; --commands prints the argv
│       ├── taxonomy.py     # check taxonomy (deterministic detectors)
│       ├── dataproducts.py # check system-boundaries + products boundaries/generate/serve (cache+parallel)
│       ├── defer.py        # `adaf defer-diff` / `defer-state` — built-vs-deferred + the CI --state plumbing
│       ├── targets.py      # `adaf list` (ls) — scope preview, hop groups, --macros/--paths/--bare
│       ├── sdaglint.py     # `adaf sdag check` — boundary-obligation lint (catalogue rule IDs)
│       ├── review.py       # `adaf review` — LLM review via GitHub Models (keyless); --post for PR comments
│       ├── report.py       # `adaf report` — per-model markdown + LLM-vs-deterministic reconciliation
│       └── checks.py       # check all (aggregator)
├── evals/                  # deepeval harness over the broken fixture (eval dep-group)
└── tests/                  # catalogue-integrity + ported unit suite
    └── multiversion/       # Docker dbt 1.11/1.12/2.0 matrix (off `make ci`; `make adaf-multiversion-ci`)
```

**Runtime-env note:** the shell-out checks (lint→sqlfluff, format, deprecations→dbt-autofix,
system-boundaries/`--select`→`dbt ls`) need `dbt`/`sqlfluff`/`dbt-autofix` on PATH. `adaf` is
therefore *consumed* as a path dev-dependency of the dbt project, so `uv run --directory
dbt-jaffleshop adaf check …` runs it alongside the dbt toolchain (wired in the Makefile/CI).
The manifest-based checks (docs/tests/doc-columns) are pure file reads and run anywhere.

## Development contract

Run from the repo root (never `cd`):

```bash
uv run --directory .github/cli/adaf adaf rules validate      # SSoT guard (must be clean)
uv run --directory .github/cli/adaf pytest                   # catalogue-integrity tests
uvx check-jsonschema --schemafile \
  .github/cli/adaf/src/adaf/rules/catalog.schema.json \
  .github/cli/adaf/src/adaf/rules/catalog.json               # standalone schema check
```

## Architecture principles (invariants a change must preserve)

- **Catalogue data loads via `importlib.resources`** (`files("adaf.rules")`), never
  a cwd-relative or repo-relative path — so it resolves identically from source and
  when installed as a `uvx` tool.
- **Output discipline:** human + log lines → stderr (`logging`); the `--json`
  payload (and nothing else) → stdout. Keeps `adaf … --json | jq` safe.
- **CLI shape:** stdlib `argparse` only; `_help` closure as each group's default
  `func`; leaves override via `set_defaults`; `main()` dispatches `args.func(args)`
  and exits with its returned code (`.claude/rules/python/cli.md`).
- **Dual DQ attribution stays in sync with the meta-schema enums.** Adding a DAMA
  or Wang–Strong dimension means updating `catalog.schema.json` enums too; the
  tests assert rule values are a subset of the declared sets.

## Extension checklist

- [ ] Adding a rule? Edit `catalog.json` only (code + both DQ attributions +
      `detection` + `boundary_class` + `doc`). Run `adaf rules validate` + `pytest`.
- [ ] Adding a command group? Wire it in `app.py` via a `_add_<group>_group` helper;
      put the handlers in `commands/<group>.py`; keep `app.py` logic-free.
- [ ] Changed a `detection` value? Make sure the matching deterministic detector
      (or its absence) is correct — a wrong tag silently routes a rule to the weaker
      checker.
