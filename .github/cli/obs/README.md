# obs — dbt observability CLI

`obs` reads the **prod** Elementary telemetry in BigQuery and renders interactive
viewers from it. The first feature is a **run Gantt chart**: every node's execution
interval for a dbt invocation, grouped into one lane per worker thread so you can
*see* parallelism and bottlenecks — with a **run picker** to step through every run in
the window and compare thread-count permutations.

It's a sibling of [`adaf`](../adaf/) — same src-layout, same argparse/`_help` CLI
shape, same "Python emits JSON → templated HTML + vanilla JS renders it" viewer
pattern (here an index + per-run bundle, there the sdag bundle).

## What it does

```
obs generate     # extract last 30 days of prod Elementary runs → tmp/obs/ (index + viewer)
obs serve        # generate, then host the viewer on http://localhost:8099
```

`generate` extracts **every run in the last `--days` window** (default 30) into an
"index + per-item" bundle (see Output below); the viewer's run picker lists them all.
Pin a single run with `--invocation-id <uuid>`.

The Gantt reads four fields from Elementary's `dbt_run_results`, one bar per node, and
joins `dbt_invocations` for the run picker's command + thread metadata:

| Gantt need | source column |
|------------|--------------------------|
| lane       | `dbt_run_results.thread_id`     |
| node       | `dbt_run_results.unique_id`     |
| bar start  | `dbt_run_results.execute_started_at` |
| bar length | `dbt_run_results.execution_time` |
| picker label | `dbt_invocations.command` + `.threads` |

## Viewer

A vanilla-JS single-page app (no build step) with two URL-routed views:

- **Overview** (`obs.html`) — a **Plotly scatter** of every run: x = run start, y = wall
  duration, colour = pass/fail, marker size = thread count. Click any point to open that
  run's detail. The pass/fail legend sits in the chart's right gutter.
- **Detail** (`obs.html?run=<id>`) — that run's thread-grouped **SVG Gantt**, always sized
  to the full width, with a **time-brush** (a dual-handle slider) to zoom into a sub-window.
  Bars are always labelled. Plus a run picker, colour-by `resource_type`/`status`, hover
  tooltips, and a collapsible **Run logs** panel (one line per node, in execution order,
  with status + the dbt/adapter message).

Navigation is **deep-linkable**: the URL updates (`?run=<id>`) as you move, Back/Forward
work, and a `?run=` link opens straight into a run's Gantt.

### Brands + theming

obs ships **three brand packs** — *FreshGreens* (lime/Poppins), *V2 AI* (amber-on-black/
Outfit), and *Josh's Karaoke Bar* (magenta-on-purple/Inter, the default) — each with light
and dark themes. A brand selector in the sidebar switches live; the choice and theme persist
in `localStorage`. The theme provider flips a `data-theme` attribute and **injects** the
active brand's `chrome` palette onto CSS variables, then re-renders the Plotly + Gantt
canvases from a parallel JS palette (canvases can't read CSS vars).

### Design tokens (single brand curate point)

All brand colour + font definitions live in **one file**,
[`src/obs/assets/design-tokens.json`](src/obs/assets/design-tokens.json): a `brands` map,
each brand carrying `fonts` + `themes.{light,dark}`, and each theme a full `chrome` palette
(the CSS variables), a `plotly` palette, and the `gantt` lane/grid/bar colours. The
`resourceColours`/`statusColours` data scales are shared across brands. Edit it, re-serve
(it's copied verbatim into the output), refresh. No code change, no rebuild.

## Auth — read-only, no keyfiles

`obs` uses the exact path as `dbt-jaffleshop/profiles.yml`'s `prod-impersonate`
output: your own gcloud ADC **impersonates** the read-scoped `dbt-dev-elementary`
service account. BigQuery mints a short-lived token; your global gcloud config is
never repointed.

One-time setup (as a developer listed in
`infra/stacks/dbt_platform/dbt-developers.yml`, so you hold
`serviceAccountTokenCreator` on the SA):

```bash
gcloud auth application-default login
```

**In CI** the runner is already authenticated as `dbt-prod` via WIF, so impersonation is
neither needed nor permitted — pass `--no-impersonate` (or set `OBS_IMPERSONATE=false`).
That's how the GitHub Pages job builds the viewer (see below).

Connection settings default to the dbt project's own (overridable by env):

| Setting           | Env override                              | Default                                            |
|-------------------|-------------------------------------------|----------------------------------------------------|
| prod project      | `DBT_BQ_PROJECT_PROD`                      | `dbt-prod-jaffleshop`                              |
| elementary dataset| `DBT_BQ_DATASET_ELEMENTARY`               | `ELEMENTARY`                                       |
| impersonated SA   | `OBS_IMPERSONATE_SA` / `ELEMENTARY_SA`    | `dbt-dev-elementary@dbt-dev-jaffleshop…`           |

## Run it

From the repo root (never `cd` — see the global working-directory rules):

```bash
uv run --directory .github/cli/obs obs serve              # interactive viewer on :8099
uv run --directory .github/cli/obs obs generate           # just write the bundle
uv run --directory .github/cli/obs obs generate --invocation-id <uuid> -o tmp/obs
```

The bundle lands in `<repo>/tmp/obs/` by default (gitignored), in the "index + per-item"
layout the viewer lazy-loads:

```
tmp/obs/
├── index.json           # run-picker + overview-scatter summaries (one row per run) + metadata
├── runs/<id>.json       # one per-run Gantt payload, fetched on selection
├── design-tokens.json   # canvas/brand tokens (copied from assets — the curate point)
├── obs.html             # the SPA shell (overview scatter + run-detail Gantt)
└── obs.js               # the SPA engine (router + Plotly overview + Gantt + theming)
```

Open `obs.html` via `serve` (file:// URLs are blocked by browsers, and the viewer
fetches `index.json`/`runs/` relatively).

## Published on GitHub Pages

The `dbt-docs` workflow publishes the viewer as a sibling surface at
`<pages-url>/obs/obs.html`, alongside the dbt docs, the sdag lineage viewer, and the
Elementary report. That job runs as the `dbt-prod` SA (WIF), so it builds with
`obs generate --no-impersonate`. Locally, `make -C dbt-jaffleshop gha-docs` reproduces
the whole Pages site (obs included) for eyeballing before a release.

## Dev

```bash
make -C .github/cli/obs ci        # lint + typecheck + test  (no warehouse, no browser, $0)
make -C .github/cli/obs fix       # format + ruff --fix      (inner loop)
make -C .github/cli/obs test      # pure transform tests over tests/fixtures/
make -C .github/cli/obs test-e2e  # Playwright e2e over the generated static SPA
```

`ci` never touches BigQuery or a browser — the transforms (`gantt.build_gantt_payload`,
`build_bundle`) are pure and tested against a seeded fixture; only `generate`/`serve` hit
the warehouse. `test-e2e` is separate (it installs chromium and needs network for the
Plotly/Tailwind CDNs): it builds a fixture bundle, serves it over a stdlib HTTP server, and
drives headless chromium to assert the overview renders, a mark click deep-links into the
Gantt (URL + view), the theme toggle flips, deep links open detail, Back returns to
overview, and the sidebar collapses.

## Module map

```
.github/cli/obs/
├── pyproject.toml          # [project.scripts] obs = obs.app:main; hatchling bundles assets/
├── src/obs/
│   ├── app.py              # argparse wiring + main(). NO business logic.
│   ├── config.py           # prod/elementary/SA defaults (env-overridable) + repo-root discovery
│   ├── elementary.py       # BigQuery client (impersonate OR direct ADC) + window queries → list[dict]
│   ├── gantt.py            # PURE transforms (build_gantt_payload, build_bundle) + write_bundle
│   ├── viewer.py           # serve() the bundle over HTTP (no-store)
│   ├── assets/             # obs.html + obs.js + design-tokens.json (vanilla SPA; {{BUILD_ID}}/{{SOURCE}})
│   ├── commands/gantt.py   # generate/serve handlers
│   └── utils/              # logging_setup
├── tests/                  # pure-transform unit tests (payload + bundle) + seeded fixture
└── e2e/                    # Playwright suite over the served static SPA (test-e2e; not in ci)
```

## Roadmap

The `generate`/`serve` shape is meant to host more observability features as they
incubate (test-result heatmaps, freshness timelines, anomaly history). Each new
feature reads its own Elementary table(s) into a JSON payload and ships a templated
viewer alongside. When a second feature lands, `generate`/`serve` graduate into a
per-feature command group (mirroring `adaf products generate/serve`).
