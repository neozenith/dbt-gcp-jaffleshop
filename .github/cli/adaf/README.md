# `adaf` — Automated Data Assurance Framework (CLI)

`adaf` CLI is the dbt pull-request gate for the **Automated Data Assurance Framework**. 

Run over __only__ the models a PR actually touches AND the models that are part of your 
**Data Product** [dbt named `--selector`](https://docs.getdbt.com/reference/node-selection/yaml-selectors?version=1.11&name=Core). 

```sh
# The dbt project lives in the dbt-jaffleshop/ subdir; run the adaf CLI from repo root like this:
uv run --directory dbt-jaffleshop adaf --help
```
----

## Key Benefits

- **Centralised Checks**: The `adaf` CLI is a collection of dbt CI quality checks like `sqlfluff`, `dbt-autofix`, etc
- **Agentic Ready**: Clear error messages, filenames and line numbers designed to close the feedback loop, with _**concise** and **precise**_ prompting to your agentic loop.
- **Zero Magic**: It will __not__ modify your code unless you opt-in and use the `--fix` flag.
- **Incremental Checking**: It is a wrapper to neatly handle `--changed-only` (default) or `--all` models.
- **Offline Deferred State Checking**: Cross compare deferred dbt states using just a target git ref like a tag or branch name.
- **Visualise Data Products**: Generate Data Product centric visualisations of data compliance.

Its one defining idea is the **`Scoped Change Set`**: rather than check ~1,200 models on
every PR, `adaf` CLI works on only the **intersection of the models you changed and a known dbt selector**.

The intersection of `dbt ls --selector <your named selector>` and `--select state:modified`. ([_See State Modified Guide._](docs/guides/state-modified-selectors.md))

----


<!--TOC-->

- [`adaf` — Automated Data Assurance Framework (CLI)](#adaf--automated-data-assurance-framework-cli)
  - [Key Benefits](#key-benefits)
  - [Onboarding](#onboarding)
  - [Quickstart Local Development](#quickstart-local-development)
    - [List Scoped Changes](#list-scoped-changes)
    - [Run the checks](#run-the-checks)
    - [Data Product System Boundaries DAG (sdag)](#data-product-system-boundaries-dag-sdag)
    - [Lint data-product boundaries (sdag check)](#lint-data-product-boundaries-sdag-check)
    - [Scaffold a per-product workflow (gha)](#scaffold-a-per-product-workflow-gha)
    - [Install the reusable composite actions (gha init)](#install-the-reusable-composite-actions-gha-init)
    - [Defer to a baseline ref](#defer-to-a-baseline-ref)
  - [Architecture](#architecture)
  - [Troubleshooting](#troubleshooting)

<!--TOC-->

---

## Onboarding

Create your **Data Product** [dbt named `--selector`](https://docs.getdbt.com/reference/node-selection/yaml-selectors?version=1.11&name=Core).

For example: `dbt-jaffleshop/selectors.yml`
```yml
selectors:
  - name: demand
    description: Demand-side data product (orders + customers marts + upstream staging).
    definition:
      union:
        - method: fqn
          value: orders
          parents: true
        - method: fqn
          value: customers
          parents: true
```


Then run:

```sh
uv run --directory dbt-jaffleshop adaf gha create demand # --force when recreating
```

This creates `.github/workflows/adaf-demand.yml`. All PRs triggering your **Data Product** will now have a PR-sticky comment with your ADAF Report:

<div align="center">
  <img src="docs/assets/demand-gha-prcomment.png" height=400px />
</div>

You can now visualise your data product similar to `dbt docs` running:

```sh
uv run --directory dbt-jaffleshop adaf sdag generate # generates static html in tmp/sdag/
uv run --directory dbt-jaffleshop adaf sdag serve    # Serves tmp/sdag/ on http://localhost:8088/sdag.html
```

<div align="center">
  <img src="docs/assets/demand-dataproduct.png" height=400px/>
</div>

## Quickstart Local Development

***tl;dr*** — everything runs from the **repo root** (the dbt project is the `dbt-jaffleshop/` subdir,
so `adaf` runs under `uv run --directory dbt-jaffleshop`):

`--selector <product>` is **required** on every check (no default — be explicit). Pick a
named selector from `dbt-jaffleshop/selectors.yml` (e.g. `demand`, `supply`):

```sh
uv sync --directory dbt-jaffleshop                        # once: editable-install `adaf` into the dbt project's venv
adaf list         --selector demand      # what WOULD be checked (changed vs main, in scope)
adaf sqlfluff     --selector demand      # lint those models      (add --fix to auto-fix in place)
adaf deprecations --selector demand      # dbt-autofix dry-run     (add --fix to apply)
adaf docscov      --selector demand      # model-description coverage
adaf testcov      --selector demand      # test coverage
adaf sdag serve                          # build + host the lineage viewer at localhost:8088
adaf sdag check                          # lint each data product's system-boundary obligations
adaf gha create   demand                 # scaffold .github/workflows/adaf-demand.yml
adaf gha init                            # install the reusable adaf-* composite actions
```

Each bare `adaf …` line above is shorthand for `uv run --directory dbt-jaffleshop adaf …`.

Short aliases: `ls` → `list`, `fluff` → `sqlfluff`, `dep` → `deprecations`.

### List Scoped Changes

**See what would be checked.** `list` resolves the `Scoped Change Set` and prints the model
files. The default scope is *changed versus `main`*; `--all` widens it to every in-scope model:

```sh
adaf list --changed-only --selector <your named selector> # --changed-only is the default
adaf list --all --selector <your named selector>
```

Output:

```
# all models that are also in selector:demand — 8 model(s)
dbt-jaffleshop/models/marts/orders.sql
...
dbt-jaffleshop/models/staging/stg_orders.sql
```

### Run the checks

The core basic check are:
- `sqlfluff` - linting and formatting
- `deprecations` - `dbt-autofix` deprecations migration checker
- `docscov` - Check models for documentation coverage
- `testcov` - checks models for test coverage.

The `sqlfluff` and `deprecations` checks take `--fix` to auto fixable changes instead of only reporting:

```sh
adaf sqlfluff --all --selector demand          # lint EVERY in-scope model (report only)
adaf sqlfluff --all --selector demand --fix    # auto-fix them in place (sqlfluff fix --force)
adaf deprecations --selector demand --fix      # apply dbt-autofix to CHANGED in-scope models
adaf docscov --all --selector demand --parse   # docs coverage (--parse refreshes the manifest first)
adaf testcov --all --selector demand           # test coverage (reuses the manifest)
```

Both `sqlfluff` and `deprecations` also take `--commands`: instead of shelling out, it prints the
exact `sqlfluff` / `dbt-autofix` command(s) it would run — one runnable line per command to stdout —
so you can inspect or run them yourself. No magic, no hidden subprocess.

```sh
adaf sqlfluff     --all --selector demand --commands   # → sqlfluff lint --format json models/…
adaf deprecations --all --selector demand --commands   # → one dbt-autofix line per folder in scope
adaf deprecations --all --selector demand --commands --fix   # the apply form (dbt-autofix without -d)
```

### Data Product System Boundaries DAG (sdag)

`sdag` builds an interactive Cytoscape viewer of every model grouped
by the data products (named selectors) it belongs to.

It works very similar to `dbt docs generate` and `dbt docs serve`:

```sh
adaf sdag generate            # write assets to tmp/sdag/ (ALL data products)
adaf sdag serve               # regenerate, then host at localhost:8088/sdag.html
adaf sdag generate --inline   # ONE standalone sdag.html (opens over file://)
```

- It renders **all** data products — there is no `--product` filter. It resolves every
  static named selector (one `dbt ls` each, ~80), so a full run can take a while.
- `--parse` is **on by default** (the viewer reflects the live graph); pass `--no-parse` to
  reuse the existing `manifest.json` and skip the slow upfront parse.
- The multi-file viewer needs `serve` (a browser blocks `fetch` over `file://`); `--inline`
  sidesteps that by embedding the JS + graph JSON into a single HTML.

### Lint data-product boundaries (sdag check)

`sdag check` enforces the contract a published data product owes its neighbours, at the
**system-boundary** nodes of the selected product. It takes the **same scope flags as every other
check** — required `--selector`, `--changed-only` (default) / `--all`, `--defer`:

```sh
adaf sdag check --all --selector demand               # whole product
adaf sdag check --selector demand                     # only the boundary nodes you changed
adaf sdag check --all --selector demand --defer --defer-ref main   # resolve members vs a baseline ref
```

The boundary is always *classified* over the product's full membership (so inside-vs-outside is
correct); the scope only decides which boundary nodes are **reported** — by default just the models
in this change set, or the whole product with `--all`.

| Rule | Boundary node | Must have |
|------|---------------|-----------|
| `MD-02` | outbound model | an enforced data contract |
| `MD-11` | outbound model | at least one exposure |
| `MD-12` | outbound model | at least one semantic model |
| `TM-AU-01` | inbound source | a freshness policy |
| `MD-07` | inbound node | a volume-anomaly test |

Silence a justified false positive in **`.adaf.yml`** (repo root) — name the rule (or `*`) and the
path glob(s) it applies to; see the commented examples in that file:

```yaml
suppress:
  - rule: MD-12
    paths: ["models/marts/legacy/**"]
    reason: "legacy mart; semantic model tracked in DTB-1234"
```

### Scaffold a per-product workflow (gha)

`gha create <product>` clones the CLI-owned workflow template (shipped as package data)
into `.github/workflows/adaf-<product>.yml`, path-filtered to that product's slice so the
workflow only triggers when that product's files change:

```sh
adaf gha create supply   # -> .github/workflows/adaf-supply.yml
```

The product must be a named selector in `selectors.yml`; comments + structure of the
template are preserved (ruamel round-trip), and it refuses to overwrite without `--force`.

### Install the reusable composite actions (gha init)

The per-product workflows call two shared composite actions (`adaf-ci` and `adaf-cleanup`).
Their canonical source ships **with the CLI** as package data;
`gha init` materialises them into `.github/actions/` and stamps each file with a version banner:

```sh
adaf gha init               # write any missing adaf-*/ actions, skip + flag drift on the rest
adaf gha init --force       # re-sync every file to the current CLI version
```

Each file gets a `# adaf:managed version=<X.Y.Z>` header (`<!-- … -->` in markdown, after the
shebang in scripts). On the next run that banner is the **version check**: a deployed file whose
version differs from the CLI's is reported as drift and left untouched unless `--force` is passed.

### Defer to a baseline ref

`--defer --defer-ref <ref>` resolves unchanged models to a **baseline manifest** parsed from
another git ref (branch/tag/sha). `adaf` checks that ref out into a throwaway worktree, runs
`dbt parse`, and caches the manifest under `tmp/adaf_cache/defer/<sha>/` — a moving branch
re-builds when it advances, a fixed tag/sha is cached forever:

```sh
adaf list --all --selector demand --defer --defer-ref main        # scope, deferring to main
adaf list --all --selector demand --defer --defer-ref prod/v5.0.0 # …or a pinned tag
```

`--target <env>` sets the dbt target for the live `dbt ls`; `--defer-target <env>` sets the target
the baseline manifest is parsed under when it differs (e.g. `--target dev --defer-target nonprod`),
defaulting to `--target`. `defer-state` builds (or reuses) that baseline and prints its `--state`
dir — handy in CI to feed a downstream `dbt build --state "$(adaf defer-state --defer-ref main)"`:

```sh
adaf defer-state --defer-ref main --target dev --defer-target nonprod
# OR 
adaf defer-state --defer-ref prod/v5.0.0 --target dev --defer-target prod
```

`ls --defer` shows **which models a selector would build vs defer** against that baseline: it splits
each listing group into a `built` sub-section (dbt's `state:modified+` — differ from the ref) and a
`deferred` one (the rest, resolved to the baseline):

```sh
adaf ls --all --selector demand --defer
# == selector models (8) ==
#   -- built (2) --
# models/.../fact_x.sql
#   -- deferred (6) --
# models/.../stg_y.sql
```

---

## Architecture

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for how the pieces fit together: the two independent
flows (the file-scoped gates' `Scoped Change Set` and the `sdag` lineage viewer), `adaf ls --flags`
build selection, the findings + sticky-PR-comment pipeline, and the reusable CI workflow. The CI job
graph itself is diagrammed in [../../../docs/adaf-ci-cd.md](../../../docs/adaf-ci-cd.md).

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `sqlfluff` errors with auth or `'NoneType' … close` | The dbt templater opens a BigQuery connection — run `gcloud auth application-default login` (ADC). The other commands don't need it. |
| `docscov` / `testcov` say `not in manifest` | The manifest is stale or missing — re-run with `--parse` (or `dbt parse`). |
| `git merge-base … failed` in CI | The base ref must be fetched first — `actions/checkout` with `fetch-depth: 0`, or `git fetch origin <base>`. |
| `error: the following arguments are required: --selector` | By design — there is no default; pass an explicit named selector from `selectors.yml`. |
| `dbt ls --selector … not found` | The named selector must exist in `selectors.yml` (run `adaf gha create` lists them on a typo). |
| `sdag: skipping … state-based selector(s)` | Expected — `state:modified` selectors aren't static data products and can't render without `--state`. |
| `port 8088 is already in use` | Another server is up — stop it or pass `adaf sdag serve --port <n>`. |
| `adaf: command not found` | Run `uv sync` from the repo root; it editable-installs `adaf` into the venv. |

