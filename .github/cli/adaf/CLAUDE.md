# Maintaining & extending `adaf`

Guidance for anyone (human or agent) changing this tool. Read `README.md` first
for what it does; this file is rationale and invariants only.

> **Status:** mid-build-out. In place: the `rules` group + catalogue (SSoT); the
> `check`/`products` groups (migrated from `dbt-jaffleshop/cicd_cli/`, byte-identical parity);
> and the `review` group (migrated from `.github/actions/dbt-testing-taxonomy-review/`, with
> the `rule_code` enum injected from the catalogue). Still to land: the deterministic taxonomy
> detectors (`check taxonomy`), the extended boundary checks, and the suppression layer — per
> [ADR-0005](../../../docs/arch/adr-0005-adaf-automated-data-assurance-framework.md).

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
├── pyproject.toml          # [project.scripts] adaf = adaf.app:main; hatchling bundles rules/ + assets/
├── src/adaf/
│   ├── app.py              # argparse wiring + main(). NO business logic. Lazy project discovery.
│   ├── __main__.py         # `python -m adaf` entry
│   ├── config.py           # PROJECT_ROOT discovery (dbt_project.yml walk-up), default paths
│   ├── logging_setup.py    # human/log → stderr; --json payload → stdout
│   ├── selection.py        # --changed-only/--all/--select/--exclude → list[Path] of models
│   ├── gitutil.py          # changed-file detection (merge-base vs --base-ref)
│   ├── manifest.py         # manifest.json → ModelDoc (description, declared columns, test_count)
│   ├── catalog.py          # catalog.json → RESOLVED warehouse columns per model
│   ├── graph.py            # data-node lineage DAG + classify_boundary() — pure
│   ├── viewer.py + assets/ # sdag Cytoscape viewer (products generate/serve)
│   ├── toollog.py          # ToolLog + run_tool(): the only way to shell out
│   ├── style.py            # ANSI colour + per-check emoji (gated on --color)
│   ├── formatting.py       # render() / emit_tool_logs() / markdown_summary()
│   ├── rules/              # the SSoT: catalog.json + catalog.schema.json + review-output.schema.json + loader
│   └── commands/
│       ├── rules.py        # `adaf rules list/show/validate`
│       ├── coverage.py     # check docs / tests / doc-columns
│       ├── deprecations.py # check deprecations (dbt-autofix)
│       ├── sqlfluff.py     # check lint / format
│       ├── dataproducts.py # check system-boundaries + products boundaries/generate/serve
│       ├── review.py       # `adaf review` — LLM review via GitHub Models (keyless); --post for PR comments
│       └── checks.py       # check all (aggregator)
└── tests/                  # catalogue-integrity + ported cicd_cli unit suite (102 tests)
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
