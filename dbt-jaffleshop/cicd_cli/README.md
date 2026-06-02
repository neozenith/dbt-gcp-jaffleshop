# cicd_cli

Centralised dev/CI automation for the dbt jaffle-shop project, as a single stdlib-argparse
Python CLI. One tool that a **developer**, an **agentic coding tool**, and **GitHub Actions**
all invoke identically — every command is a read-only gate that exits non-zero on failure,
emits `--json` for machines, and surfaces the underlying tool's raw logs so the failure is
*actionable*.

## Running it

```bash
# from the dbt project root (dbt-jaffleshop/)
uv run -m cicd_cli check --help

# from the repo root
uv run --directory dbt-jaffleshop -m cicd_cli check --help
```

(The package is `cicd_cli` — underscore, not hyphen — because Python's `-m` can't import a
hyphenated name. It's found via cwd-on-`sys.path`; both invocations set the cwd to the dbt
project root.)

## Commands

```
cicd_cli check {deprecations,lint,format,docs,doc-columns,tests,system-boundaries,all}
```

| Command | What it checks | Underlying tool | `--fix`? |
|---------|----------------|-----------------|----------|
| `deprecations` | dbt deprecated syntax in the model folders | `dbt-autofix` | ✅ applies the rewrite |
| `lint` | full SQLFluff ruleset | `sqlfluff lint` / `fix` | ✅ `sqlfluff fix` |
| `format` | layout + keyword-case subset | `sqlfluff lint --rules …` / `format` | ✅ `sqlfluff format` |
| `docs` | every selected model has a **model** description | `manifest.json` | — |
| `doc-columns` | every **resolved (actual warehouse) column** has a description | `catalog.json` + `manifest.json` | — |
| `tests` | every selected model has ≥1 test | `manifest.json` | — |
| `system-boundaries` | every **system-boundary node** of a data product has ≥1 test | `manifest.json` + `selectors.yml` | — |
| `all` | runs all of the above over one selection | — | — |

> **`system-boundaries` selects by data product, not by changed files.** Every other check operates on a
> model-file selection (`--changed-only`/`--select`); `system-boundaries` operates on the named selectors
> in `selectors.yml`, so it takes `--selectors`/`--product` instead. `check all` still includes it — but
> it always runs over **every** data product there, ignoring the file scope (so the PR comment always
> carries a `system-boundaries` row). It can also be run on its own as a standalone gate.

## Data products: system-boundary analysis

```
cicd_cli products boundaries [--product NAME ...] [--show-passes] [--json]
```

A **data product** is a named selector in `selectors.yml` (e.g. `supply`, `demand`). This command
classifies each node *inside* a data product by where it sits on the product's **system boundary**:

| Class | Meaning | Where a data contract lives |
|-------|---------|------------------------------|
| **inbound** ⬇ | has a parent outside the product (or is a source/root) | data **entering** the product |
| **outbound** ⬆ | has a child outside the product (or is a final leaf) | data the product **publishes** |
| **both** ⇅ | crosses in *and* out — typically a node shared by two products | both directions |
| **internal** · | fully interior; no lineage crosses the boundary here | no external contract |

Membership is resolved by dbt itself (`dbt ls --selector`), so the `+`/`parents` graph operators are
honoured and upstream **sources** count as inbound boundaries. Only data nodes (model/source/seed/
snapshot) are classified — tests and semantic models are excluded as attachments. By default only the
boundary nodes are shown; `--show-passes` also lists the `internal` ones. `--json` emits the full
classification (including each node's external parent/child `unique_id`s) for downstream tooling.

```bash
cicd_cli products boundaries                       # all data products, boundary nodes only
cicd_cli products boundaries --product demand       # one product
cicd_cli products boundaries --show-passes           # include internal nodes
cicd_cli products boundaries --json | jq '.products[]'
```

`products boundaries` is read-only (it never gates) — it's the descriptive view. The gate built on it
is **`check system-boundaries`**:

```
cicd_cli check system-boundaries [--product NAME ...] [--show-passes] [--json]
```

It fails when any **boundary** node (inbound / outbound / both) of a data product has **zero tests** —
the test being the enforceable half of the data contract at the product's edge. Internal nodes are not
gated. Sources count: an untested raw source is an untested inbound boundary. Failures-only by default;
`--show-passes` lists the already-tested boundary nodes too.

```bash
cicd_cli check system-boundaries                      # gate every data product; exit 1 if any boundary is untested
cicd_cli check system-boundaries --product demand     # gate one product
cicd_cli check system-boundaries --json | jq '.results[] | select(.ok==false)'
```

### Interactive viewer (`products generate` / `serve`)

```
cicd_cli products generate [--product NAME ...] [-o DIR]
cicd_cli products serve     [--product NAME ...] [-o DIR] [-p PORT]
```

`generate` builds an [sdag](#) — a "super-DAG" — viewer: it renders the **whole lineage** with the data
products overlaid, both as compound boxes around their members (full graph) and as collapsed
super-nodes with weighted cross-product edges (super graph). It writes four files into the output dir
(default `tmp/sdag/`): `full_graph.json`, `super_graph.json`, and a self-contained `sdag.html` + `sdag.js`
(Cytoscape.js + dagre via CDN). `serve` regenerates, then hosts the bundle with no-cache headers.

```bash
cicd_cli products serve                 # → http://localhost:8088/sdag.html
cicd_cli products generate -o tmp/sdag  # just write the assets; open sdag.html yourself
```

Unlike the boundary checks, the viewer shows **every** entity (tests, sources, semantic models), not
just data nodes — picking a selector in its sidebar filter highlights that product's inbound/outbound
boundary nodes and the 1-hop external halo. The assets live under `tmp/` (gitignored); regenerate any
time. A monotonic `build_id` is stamped into every file and shown in the sidebar so a stale browser tab
is obvious.

## Selecting which models to check

Every command takes the same selection flags. **Scope** (mutually exclusive):

- `--changed-only` *(default)* — models changed vs `--base-ref` (default `main`), in any git
  state (committed, staged, unstaged, untracked).
- `--all` — every `models/**/*.sql`.

**Filter** (optional, repeatable, resolved by `dbt ls` — full dbt selector grammar):

- `--select <selector>` — narrow to a dbt selection (multiple `--select` union, like dbt).
- `--exclude <selector>` — subtract a dbt selection.

The filter intersects the scope:

```bash
cicd_cli check lint                          # changed models (vs main)
cicd_cli check lint --base-ref origin/main   # changed vs a CI base ref
cicd_cli check lint --all                    # every model
cicd_cli check lint --all --select staging   # every staging model
cicd_cli check docs --changed-only --select tag:nightly --exclude stg_orders
```

## Fixing

`--fix` turns a check into an apply, where the tool supports it:

```bash
cicd_cli check lint --fix          # sqlfluff fix on changed models
cicd_cli check format --fix --all  # sqlfluff format across all models
cicd_cli check deprecations --fix  # dbt-autofix rewrites the deprecated syntax
cicd_cli check all --fix           # fixes deprecations + lint + format in one pass
```

The fixable checks are `deprecations`, `lint`, and `format`. `check all --fix` propagates
`--fix` to those three and is a **no-op** for `docs`/`doc-columns`/`tests` (descriptions and tests can't be
synthesised), which keep reporting their gaps.

## Output, and getting a signal an agent can act on

- **Human** (default): a concise, **emoji-labelled, colour-coded** verdict per check
  (`🧹 deprecations`, `🔍 lint`, `🎨 format`, `📄 docs`, `📑 doc-columns`, `🧪 tests`), written to **stderr**, with
  ✅/❌ in green/red and each section clearly separated. **Failures-only** — passing per-item
  results (e.g. each documented/tested model) are suppressed; a passing check collapses to a
  single ✅ line. Pass `--show-passes` to see passing results too. Colour follows `--color`
  (`auto` = TTY only, plus `always`/`never`; `NO_COLOR` is honoured); when off, tool transcripts
  are ANSI-stripped so piped output stays clean.
- **`--json`**: the full machine payload to **stdout** (so `... --json | jq` is clean). Always
  includes every result (passes and failures) plus a `logs` array of the raw tool invocations.
- **Raw tool logs**: on **failure**, the underlying tool's **native** transcript — exactly what
  you'd see running it by hand, **ANSI colour and all** (captured via a pseudo-terminal) — is
  printed below the verdict. `--show-logs` forces it even on success. This is the actionable
  detail: SQLFluff's coloured per-violation `L:line | P:pos | rule` output (and, after
  `check lint --fix`, the "lint for unfixable violations" section listing what you must fix **by
  hand**), or dbt-autofix's human-readable `Refactored <file>: …` output (not the JSON we parse
  internally for detection).

```bash
cicd_cli check lint --all --json | jq '.logs[0].stdout'      # raw violations for an agent
cicd_cli check lint --fix --all                              # remaining unfixable violations print on failure
```

`docs`/`tests` need a manifest: pass `--manifest <path>` (default `target/manifest.json`) or `--parse`
to rebuild it via `dbt parse`. `doc-columns` additionally needs **`catalog.json`** for the *resolved*
(actual warehouse) column set — `--catalog <path>` (default `target/catalog.json`) or `--docs-generate`
to (re)build manifest **and** catalog via `dbt docs generate` (which needs a warehouse build/connection,
unlike `dbt parse`). If the catalog is absent, `doc-columns` fails loud — it does **not** silently fall back
to YAML-declared columns. In `check all`, a missing catalog is a visible doc-columns failure; the other gates
still run.

## Exit codes

`0` pass · `1` a check failed (or a tool errored) · `2` argparse usage error.

## Makefile

`make lint` / `lint-fix` / `format` / `format-check` / `deprecations-check` / `docs-coverage` /
`doc-columns-coverage` / `tests-coverage` / `checks` all delegate here. See `dbt-jaffleshop/Makefile`.

## PR checks (CI)

`.github/workflows/dbt-cicd-checks.yml` runs `check all` on every PR (WIF → dbt-test SA, then
`dbt docs generate` for the manifest + catalog), writes the summary table with `check all --md
<file>`, and posts a single **self-updating** PR comment that links to the run's logs — the
comment is the digest, the logs hold the full per-file / per-violation detail. (`doc-columns` is
accurate only once the models are built; see the note in the workflow file.)

## Extending it

See [`CLAUDE.md`](./CLAUDE.md) for the architecture and a step-by-step recipe for adding a new
check.
