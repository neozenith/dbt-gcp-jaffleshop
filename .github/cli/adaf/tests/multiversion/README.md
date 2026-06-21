# multiversion — dbt version-matrix integration suite

Builds **one Docker image per pinned dbt version — all from a SINGLE, ARG-parametrised Dockerfile**
(`docker/Dockerfile`), `dbt parse`s the tiny committed `fixture/` project under that version, runs adaf's
read-only gates against the resulting artifact, and snapshots their stdout / stderr / exit codes against
a golden per capability per version LINE (`goldens/<capability>/<series-id>.txt`). A diff is the
regression signal: if a new dbt parser drops, renames, or *rejects* a field one of adaf's projections
reads, the snapshot diverges and the run fails loudly — escalators-not-stairs, never a silent skip.

> **Bootstrap:** no goldens are committed yet. The first run on a fresh checkout (or whenever a new
> version line resolves) must **rebaseline** to create them — `adaf-multiversion-ci` asserts
> `golden.exists()` and fails loudly with a "re-baseline" message until you do. This is by design:
> goldens are version/behaviour snapshots that can only be produced by actually running the matrix on
> a Docker host, so they are generated, reviewed, then committed — never hand-authored.

The harness is driven by **testcontainers** (`test_multiversion.py`), needs a running **Docker daemon**,
and is **off `make ci`**.

## Run it

```bash
# First time (or after a new version line lands): create + review the goldens, then commit them.
make -C .github/cli/adaf adaf-multiversion-rebaseline    # build + run every version, WRITE goldens
# Thereafter: assert the committed goldens still hold (the regression gate).
make -C .github/cli/adaf adaf-multiversion-ci            # build + run every version, assert vs goldens
```

Under the hood (the target just selects the marker — nothing extra to install, see below):

```bash
uv run --directory .github/cli/adaf \
  pytest tests/multiversion/test_multiversion.py -m multiversion -s -v
```

First run builds the images (minutes + PyPI bandwidth); later runs reuse Docker's layer cache. Build
contexts, per-version `result.json`, and logs land under the repo's `tmp/multiversion/<series-id>/`
(project-local tmp, never system `/tmp`).

### Persisted parse artifacts (`tmp/multiversion/<series-id>/target/`)

After each version parses the fixture, the harness `docker cp`s that container's `/fixture/target/`
back onto the host at **`tmp/multiversion/<series-id>/target/`**, so every version's parsed artifacts
survive the run for inspection — even when a golden assertion fails (the copy runs in `_run_engine`
*before* the assertion). The host dir is wiped at the start of each run so stale artifacts can never
mislead.

The copy uses docker-py `container.get_archive("/fixture/target")` (`docker cp` semantics) rather than
a bind-mount: it captures whatever the engine actually wrote — a JSON `manifest.json`, or a v2.0
engine's own artifact tree — as an exact tar of container state, with no Docker-Desktop bind-mount or
root-ownership quirks. The container therefore runs **detached** (not one-shot `--rm`) so it survives
long enough to copy out before removal; its stdout JSON is read exactly as before.

## Why it stays off `make ci` (and why that is NOT requirement degradation)

`make ci` must remain fast, offline, and Docker-free — but **not** by making the harness optional.
`testcontainers` (+ the `docker` SDK it drives) is a **hard dev dependency** (`[dependency-groups] dev`,
the same group as pytest/ruff/mypy), so the test env ALWAYS has it and `test_multiversion.py` imports it
unconditionally at module top — **no `importorskip`**. If it were ever missing, the suite ERRORS LOUDLY;
it never skips.

What keeps Docker off `ci` is a single, honest lever: the suite is marked `multiversion` and pyproject's
`addopts = "-m 'not multiversion'"` **deselects** it by default (a CLI `-m multiversion` in the target
re-selects it). So `make ci` collects the module, *deselects* the version cases, and never touches
Docker — environment economy (the cheap gate doesn't run the expensive tests), not requirement
degradation (the dependency is present and the tests are real).

## The matrix — version LINES, resolved from PyPI (auto-tracking)

The matrix is **not** a list of fixed pins. It is one row per dbt *version line* (a `Series` in
`test_multiversion.py`), and each line resolves its concrete build **when the test runs**. So a new
prerelease — or the GA that supersedes it — **auto-enrols the moment it lands**, with no edit to this
suite. The pip lines are a plain pip install of `dbt-core` + `dbt-duckdb` into an isolated venv; the
`dbt-fusion` line is different — it installs the Rust **Fusion engine** from the public CDN (not PyPI)
and is the row that exercises the new **v20 parquet** artifact set (see
[`docs/dbt-fusion-artifacts.md`](../../docs/dbt-fusion-artifacts.md)). The fixture is migrated to be
forward-compatible (see below), so all lines parse clean and produce identical *gate* output (only the
`parse` golden differs per row):

| Line id (golden key) | Engine / source | Prereleases? | Manifest read | Resolves to today |
|-----------|-----|------|--------|---------|
| `dbt-1.11` | `dbt-core` (PyPI), classic Python parser | no — latest stable patch | JSON `manifest.json` | `dbt-core==1.11.11` |
| `dbt-1.12` | `dbt-core` (PyPI), `--use-v2-parser` (Rust v2 parser) | yes (GA wins when out) | JSON `manifest.json` | `dbt-core==1.12.0b3` |
| `dbt-2.0` | `dbt-core` 2.0 (PyPI) — still a **v12 JSON** manifest, no parquet | yes (GA wins when out) | JSON `manifest.json` | `dbt-core==2.0.0a2` |
| `dbt-fusion` | **Fusion** Rust engine (CDN installer), `--write-index` | n/a — floats to CDN latest | **parquet** (`metadata/parse/*.parquet`) | `dbt-fusion==2.0.0-preview.190` |

**How auto-tracking works.** A line that `track_prereleases` takes the newest alpha/beta/rc that matches
its specifier; because a GA is a *higher* version than any of its prereleases, the line auto-promotes
prerelease → GA the instant the GA publishes — no specifier change needed. The stable `dbt-1.11` line
disallows prereleases and just floats to the latest `1.11.x` patch. `dbt-duckdb==1.10.1` co-installs
cleanly with all three lines today; it is a per-line property, so bump it there if a future dbt-core
needs a newer adapter.

**Discovery is loud, never silent.** Versions come from `https://pypi.org/pypi/dbt-core/json`, fetched
once per run **inside the test body** (so `make ci`, which deselects this suite before any body runs,
never touches the network). If PyPI is unreachable, or no release matches a line's specifier, the suite
**raises** — there is no fallback to a stale hard-coded pin, because that would silently stop the matrix
from tracking new releases.

**A newly-resolved version → one deliberate re-baseline.** Goldens are keyed by the *stable line id*
(`dbt-1.12`), not the floating version. The gate goldens (`list` / `docs` / `tests` / `sdag-check`)
are version-independent, so a new patch with unchanged behaviour **re-passes them automatically**; only
the version-bearing `parse` golden differs, so a freshly-resolved prerelease/GA surfaces as a single
`parse` mismatch. Re-baseline it (below) and the commit becomes the record of *which* version the line
now tracks. A genuine behavioural change (a dropped manifest field, a new parquet artifact kind) still
diverges a gate golden and fails loudly — exactly the regression signal the suite exists for.

### Adding or changing a line

Add a `Series(...)` to `SERIES` (or edit one) — its `specifier` and `track_prereleases` define what it
tracks, `spec_profile` (`legacy` | `inline`) picks the fixture's semantic-layer variant, and
`parse_flags` / `adaf_install_spec` carry the parser flag and adaf extra. Then run the rebaseline target
to write its goldens. No Dockerfile or staging-code change.

### The two breaking changes the harness pinned down

The Rust parser (1.12's `--use-v2-parser` and the 2.0 engine) is schema-strict where the classic Python
parser (1.11) was lenient. Two un-migrated constructs broke the newer engines — both are **fixed in the
fixture** so the matrix exercises the forward-compatible project a real upgrade produces:

1. **Source-level config keys** (`tags` / `loaded_at_field` / `freshness`) must be nested under
   `config:`. Loose, they are a hard `UnusedConfigKey (dbt1060)` **error** on the Rust parser (parse
   exit 2 on 1.12 `--use-v2-parser`, `dbt ls` exit 1 on 2.0) — the classic parser tolerated them. The
   nested form parses on **all three** and still lands the freshness in the manifest. (`dbt-autofix`
   does this.)
2. **The semantic-layer spec is version-exclusive.** The legacy standalone `semantic_models:` resource
   is dbt Core 1.6–1.11 only (2.0 drops it with warning `dbt1157`); the inline `semantic_model:` block
   on a model is 1.12+/2.0 only (1.11 silently ignores it). **No single YAML satisfies both 1.11 and
   2.0.** The fixture therefore carries *both* forms as per-profile variants (see below), so MD-12 is
   correct on every engine.

## The fixture

`fixture/` is a deliberately tiny dbt project (duckdb profile, no warehouse — `dbt parse` opens no
connection) carrying exactly enough to exercise every gate. Its one data product is the `matrix_demo`
selector (`tag:matrix_demo`):

- a **source** (`raw.orders`) with a freshness policy but no volume-anomaly test → inbound boundary
  node that satisfies **TM-AU-01** and **violates MD-07**;
- an interior staging model (`stg_orders`, documented + tested) → `inner` node, no obligations;
- a fully-governed outbound mart (`dim_customers`: description, test, enforced contract, exposure,
  semantic model) → **clean** outbound node;
- a partially-governed outbound mart (`fct_orders`: enforced contract + exposure, but no semantic
  model, description, or tests) → **violates MD-12**, and the docs / tests coverage gap;
- an untagged MetricFlow time-spine model kept *out* of the product.

So every engine's golden encodes the same known-answer mix across all four gates: `list` → 3 models,
`check docs` 1/3, `check tests` 1/3, and `sdag check` reporting exactly **MD-12** (`fct_orders`) +
**MD-07** (`raw.orders`).

### Per-engine fixture variants (`__<engine-id>` suffix)

Because the semantic-layer spec is version-exclusive (above), the fixture carries **both** spec forms as
**profile**-suffixed variants, and `_stage_fixture` overlays the one matching a line's `spec_profile`
(suffix stripped) into its build context. Keying on the profile (`legacy` | `inline`), not a version id,
is what lets a line's pin float without renaming any fixture file:

| File | Staged for profile | Spec |
|------|-----------|------|
| `_semantic_models__legacy.yml` | `legacy` (the `dbt-1.11` line) | legacy standalone `semantic_models:` |
| `_marts__legacy.yml` | `legacy` | marts with **no** inline semantic model |
| `_marts__inline.yml` | `inline` (the `dbt-1.12` + `dbt-2.0` lines) | marts with the inline `semantic_model:` block |

Unsuffixed files (`_staging.yml`, `_exposures.yml`, `_metricflow.yml`, `dbt_project.yml`, …) are shared
by every line. To add a line whose spec differs, set its `Series.spec_profile` and (if it is a brand-new
profile) drop in the `__<profile>`-suffixed variants — no staging-code change.

## Architecture

```
tests/multiversion/
├── test_multiversion.py     # the testcontainers pytest harness (marker: multiversion)
├── docker/
│   ├── Dockerfile           # the ONE ARG-parametrised image for EVERY version (built per row, differing buildargs)
│   └── harness.py           # stdlib-only in-container runner, COPYed into the image (the ENTRYPOINT)
├── fixture/                 # the tiny dbt project parsed under each line (+ per-profile __<profile> variants)
└── goldens/<capability>/<series-id>.txt   # one snapshot per capability per LINE (see below)
```

Goldens are split **by capability** and keyed by the **stable line id** (not the floating version) so a
single gate diffs straight across lines:

```
goldens/
├── parse/<series-id>.txt        # the ONLY version-bearing golden: versions, manifest kind, parse exit
├── list/<series-id>.txt
├── docs/<series-id>.txt
├── tests/<series-id>.txt
└── sdag-check/<series-id>.txt    # ("sdag check" → slug "sdag-check")
```

Each gate file holds only that gate's invocation + exit/stdout/stderr and is **version-independent**, so
a line's pin floating to a new patch re-passes it untouched (a `diff goldens/list/dbt-1.11.txt
goldens/list/dbt-2.0.txt` shows pure capability drift). Only `parse/<series-id>.txt` carries the resolved
version string, so it is the one golden a freshly-resolved prerelease/GA re-baselines — the deliberate
record of which version the line now tracks.

### One Dockerfile, every version — the build ARGs

There is no per-version Dockerfile. `test_multiversion.py` defines a frozen `Series` per line of the
matrix; at test time each `Series.resolve()` pins it to a concrete `Engine`, whose `build_args()`
produces the `buildargs` dict handed to `docker/Dockerfile`. Every row is a pip install of dbt-core + an
adapter into an isolated venv — one `RUN`, no install-kind branching. The full ARG set:

| ARG | Purpose |
|-----|---------|
| `ENGINE_NAME` | the RESOLVED version id, baked as `$ENGINE_NAME` for `harness.py` (e.g. `dbt1-12-0b3`) |
| `DBT_CORE_SPEC` | pip spec for dbt-core (e.g. `dbt-core==1.11.11`) |
| `DBT_ADAPTER_SPEC` | pip spec for the adapter (e.g. `dbt-duckdb==1.10.1`) |
| `PARSE_FLAGS` | extra `dbt parse` flags baked for `harness.py` (e.g. `--use-v2-parser`) |
| `ADAF_INSTALL_SPEC` | adaf install target: `/opt/adaf_pkg` or `/opt/adaf_pkg[fusion]` (parquet reader) |
| `SELECTOR` | adaf selector the gates run under (`matrix_demo`) |
| `PIP_PRERELEASE` | uv `--prerelease`: `disallow` / `allow` (`allow` for the beta + alpha rows) |

`DBT_BIN` (`/opt/dbt-venv/bin/dbt`) and `VERSION_PKGS` (`dbt-core,dbt-duckdb`) are now **invariant** — every
row is a pip venv — so they are baked straight into the image's `ENV` rather than derived per row.

- **The image** builds two isolated venvs: adaf in its own Python 3.12 venv, the dbt engine in its own.
  `harness.py` puts the engine's `dbt` first on `PATH` so the `dbt ls` adaf shells out to is the
  **same** engine that wrote the manifest.
- **`harness.py`** `dbt parse`s the fixture, detects whether the artifact is JSON (`manifest.json`)
  or parquet (a `*.parquet` dir — adaf's `load_artifact` handles both), runs all four gates
  (`list`, `check docs`, `check tests`, `sdag check` — over `--all` / `--selector matrix_demo`), and emits ONE
  JSON document on stdout. It always exits 0: a gate's non-zero exit is *data*, so a parse/engine
  failure is captured in the golden, not masked as a crash.
- **`test_multiversion.py`** stages a minimal build context under `tmp/`, builds the image with
  testcontainers `DockerImage(..., buildargs=engine.build_args())`, runs the (detached) container,
  `docker cp`s its `/fixture/target/` out to `tmp/multiversion/<series-id>/target/` (see *Persisted parse
  artifacts* above), splits the JSON into one golden per capability, and asserts each equals
  `goldens/<capability>/<series-id>.txt` (or rewrites them under `ADAF_GOLDEN_UPDATE=1`).

Container paths (`/fixture`, `/opt/...`) and exact version pins make the golden fully deterministic —
no path/normalisation needed.

## Re-baseline procedure (deliberate, never automatic)

Goldens are per-version and re-baselined only on a **deliberate** change — a version pin bump *or* an
intended change to adaf's gate output. (adaf is installed from `src/` at build time, so a real adaf
change legitimately shifts these goldens; re-baseline in the same change.)

1. Run `make -C .github/cli/adaf adaf-multiversion-ci`; read the failing diff (or inspect
   `tmp/multiversion/<series-id>/result.json`).
2. Confirm every changed line is **intended** (a dbt behaviour change or an intended adaf change), not
   a regression.
3. Re-baseline with `make -C .github/cli/adaf adaf-multiversion-rebaseline` and **commit the new
   golden in the same change**, with the diff explained in the commit message.

Never auto-overwrite a golden to make a red run green — the diff *is* the finding.
