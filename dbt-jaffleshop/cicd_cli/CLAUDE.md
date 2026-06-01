# Maintaining & extending `cicd_cli`

Guidance for anyone (human or agent) changing this package. Read `README.md` first for what
it does; this file is about how it's built and how to add to it without breaking the grain.

## The one idea that holds it together: a **Report**

Every check produces a *Report* object. The renderer (`formatting.render`) and the `check all`
aggregator (`commands/checks.py`) are generic over that shape — they never know which check
they're rendering. A Report exposes:

| Member | Type | Purpose |
|--------|------|---------|
| `ok` | `bool` (property) | did the check pass? drives the exit code |
| `to_dict()` | `-> dict` | the `--json` payload |
| `human_lines(show_passes=False)` | `-> list[(int, str)]` | `(logging-level, message)` pairs — the concise verdict |
| `logs` | `list[ToolLog]` *(optional)* | raw transcripts of the underlying tool calls |

`human_lines()` is the **summary** (verdict + which files). The **raw** tool output lives in
`logs` and is printed separately (on failure, or with `--show-logs`). Keep that split — never
dump raw tool output into `human_lines()`.

Output is **failures-only by default**: `human_lines(show_passes=False)` must suppress passing
per-item detail (a passing check collapses to its one-line verdict) and show full detail only for
failures. `show_passes=True` restores the passing rows. `--json` (`to_dict`) is unaffected — it
always carries every result.

## Module map

```
cicd_cli/
├── app.py              # argparse wiring + main(). NO business logic.
├── config.py           # PROJECT_ROOT, DEFAULT_BASE_REF, DEFAULT_MANIFEST, MODEL_GLOB
├── selection.py        # --changed-only/--all/--select/--exclude → list[Path] of models
├── gitutil.py          # changed-file detection (the Makefile CHANGED_MODELS, ported)
├── manifest.py         # read target/manifest.json → ModelDoc (description, DECLARED columns, test_count)
├── catalog.py          # read target/catalog.json → RESOLVED (actual warehouse) columns per model
├── toollog.py          # ToolLog + run_tool(): the ONLY way to shell out to a tool
├── style.py            # ANSI colour + per-check emoji for OUR output (gated on --color)
├── formatting.py       # render() + emit_tool_logs() + markdown_summary(): human↔json↔md output
└── commands/
    ├── deprecations.py # dbt-autofix
    ├── sqlfluff.py     # lint + format
    ├── coverage.py     # docs + tests (manifest), columns (catalog-resolved + manifest)
    └── checks.py       # `check all` aggregator
```

## Non-negotiable conventions (project rules)

- **CLI**: stdlib `argparse` only (`.claude/rules/python/cli.md`). Every group uses
  `set_defaults(func=_help(parser))` + `add_subparsers(required=False)`; leaves override `func`.
- **Python** (`.claude/rules/python/RULES.md`): imports at the **top** (no nested imports);
  `pathlib` not `os.path`; `logging` not `print` for messages; `%`-style log args.
- **Tests** (`.claude/rules/python/tests.md`): **no mocks/patches**. Test pure functions with
  real data; shell out to real commands (e.g. `git --version`) when you need a subprocess.
- **uv**: run everything via `uv run` (`.claude/rules/python/uv.md`).
- **Output discipline**: human/log lines → **stderr** (via `logging`); the `--json` payload →
  **stdout**. This is what makes `... --json | jq` safe.
- **Styling**: build `human_lines` from the `style` helpers (`style.section(name)`,
  `style.passed/failed/pass_item/fail_item`) and add the check's emoji to `style.EMOJI`. Never
  hard-code ANSI or `✓/✗` — `style` gates colour on `--color` and keeps every section uniform.

## How to add a new check (e.g. `check freshness`)

1. **Create `commands/freshness.py`** with a Report dataclass implementing `ok`,
   `to_dict()`, `human_lines()`, and (if it shells out) a `logs: list[ToolLog]` field
   (`field(default_factory=list)`).
2. **Shell out only via `run_tool`** (`toollog.py`) so the command/stdout/stderr/exit-code are
   captured. Attach the returned `ToolLog`(s) to the report's `logs`. Pass `tty=True` to capture
   the tool's native coloured output. Never call `subprocess.run` directly in a command module.
3. **Resolve models via `selection`**: `sel = selection.from_args(args)` →
   `files = selection.resolve_model_files(sel)`; pass `scope = selection.describe(sel)` into the
   report for its header.
4. **Write a `cmd(args)` handler** that builds the report and returns
   `render(report, as_json=args.as_json, show_logs=args.show_logs)`.
5. **Wire it in `app.py`**: add a `check_sub.add_parser("freshness", …)`, call `_add_selection`
   (and `_add_fix` only if it can fix, `_add_manifest` only if it needs the manifest), then
   `set_defaults(func=freshness.cmd)`.
6. **Add it to `check all`** in `commands/checks.py` if it should be part of the aggregate.
7. **Test it** under `pytests/cicd_cli/test_freshness.py` — unit-test the pure evaluation with a
   constructed input; add a CLI smoke test only if the wiring is non-trivial.

Keep the pure logic (evaluation) separate from the I/O (git, subprocess, manifest read) so the
core is testable without a warehouse — that's why `evaluate_docs`/`evaluate_tests`/
`parse_autofix_output` take plain data and return Reports.

## Gotchas (each cost real debugging once)

- **`dbt-autofix` always exits 0**, even when it finds deprecations. Failure is derived from its
  `--json` `refactors` key, not its exit code. A genuine non-zero exit is re-raised.
- **Capture stderr.** The dbt-templater's *compile* errors (a model that won't render) go to
  stderr; SQLFluff violations go to stdout. `run_tool` keeps both — don't drop stderr.
- **Native coloured logs come from a pty.** sqlfluff/click and dbt-autofix/rich strip ANSI when
  piped, so `run_tool(..., tty=True)` runs the tool on a pseudo-terminal to capture its native
  coloured output (stdout+stderr merge in that mode). sqlfluff uses it; so does dbt-autofix's
  display run.
- **dbt-autofix is run twice, by design.** Detection is a robust JSON **dry-run** (`-d --json`,
  always non-mutating) parsed into `records`; the log is a *separate* native run —
  dry-run in check mode, the real **apply** in `--fix`. The detection run never mutates, so in
  fix mode the file is rewritten exactly once (by the native run). Don't collapse these into one
  call — `--json` and native output are mutually exclusive, and a second apply would be a no-op.
- **`DBT_PROFILES_DIR`** is forced to `PROJECT_ROOT` in `main()` (mirrors the Makefile). An
  inherited value (e.g. the repo root) otherwise makes dbt fail with "could not find profile".
- **`--select`/`--exclude` shell out to `dbt ls`**, which needs the dbt profile env (project IDs
  from `.env`, loaded via `load_dotenv()` in `main()`). `--changed-only`/`--all` are pure git/FS.
- **`columns` is catalog-resolved and warehouse-dependent.** It joins `catalog.json` (actual
  columns — `dbt docs generate`, needs a warehouse build) with `manifest.json` (descriptions).
  `manifest` alone only knows YAML-*declared* columns, which understates the denominator. A
  missing catalog **fails loud** (no silent declared-only fallback); `check all` catches that and
  renders a visible `ColumnsReport(error=…)` so the other gates still run. Match catalog↔manifest
  column names case-insensitively (warehouse vs YAML casing).
- **Project-global deprecations** (`dbt_project.yml`) are reported by `dbt-autofix` in *every*
  per-dir scan; `deprecations.run()` dedupes records by `file_path`.
- **cwd-on-`sys.path`**: the package isn't an installed dist; `-m cicd_cli` finds it via cwd. The
  pytest `pythonpath=["."]` and `[tool.pyright] extraPaths=["."]` in `pyproject.toml` give the
  test runner and type checker the same reach.

## Running the tests

```bash
uv run --directory dbt-jaffleshop pytest pytests/cicd_cli/      # this package's tests only
uv run --directory dbt-jaffleshop pytest                        # full suite (incl. macro tests)
```
