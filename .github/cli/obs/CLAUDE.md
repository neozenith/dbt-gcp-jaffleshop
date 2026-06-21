# Maintaining & extending `obs`

Guidance for anyone (human or agent) changing this tool. Read `README.md` first for
what it does; this file is rationale and invariants only.

> **Status:** v0. In place: the Gantt viewer (`generate`/`serve`) over Elementary's
> `dbt_run_results` + `dbt_invocations`, with a 30-day multi-run bundle, a run picker,
> light/dark/system theming from `design-tokens.json`, and a collapsible sidebar.
> Published to GitHub Pages by the `dbt-docs` workflow. Born by promoting a one-off
> `tmp/elementary_gantt/` analysis script into a proper CLI sibling of `adaf`.

## The one idea that holds it together: extract → JSON → templated viewer

The Python half **never renders pixels**. It queries BigQuery (`elementary.py`),
transforms rows into a JSON bundle (`gantt.py`, pure), and writes it next to a
templated HTML+JS viewer (`gantt.write_bundle`). All visual logic lives in
`assets/obs.js` — a vanilla-JS SPA (no build step): an overview Plotly scatter and a
run-detail SVG Gantt, URL-routed via `?run=<id>`. This is the same split as `adaf`'s
sdag viewer — and it's what keeps `make ci` free: the transforms are unit-tested
against a seeded fixture with **no warehouse** (only `generate`/`serve` touch BigQuery),
while the browser behaviour is covered by the separate `make test-e2e` Playwright suite.

**Never** render the chart server-side or inline data into the HTML. The artifact
boundary is the JSON bundle (`index.json` + `runs/<id>.json`) — independently
inspectable, diffable, replottable.

The bundle uses the repo's **"index + per-item" manifest shape**
(`.claude/rules/python/helper_scripts/cloud_enabled_manifest_pattern.md`): a light
`index.json` (one summary row per run) + lazy-loaded `runs/<id>.json`. The viewer
fetches the index, fills the run picker, and pulls each run only on selection — so it
scales as the thread-permutation sweep accumulates runs.

## Architecture principles (invariants a change must preserve)

- **Pure transform.** `gantt.build_gantt_payload(rows, …)` takes plain dicts and
  returns a JSON-able dict — no I/O, no clock-reads beyond what's passed in. Keep it
  that way so `tests/test_gantt.py` can assert exact wall/CPU/offset numbers.
- **I/O is quarantined in `elementary.py`.** The BigQuery client and queries live
  there and return `list[dict]` of native values. Nothing else imports `google.*`.
- **Read-only, fail-loud, two auth modes.** Local impersonates the read-scoped
  `dbt-dev-elementary` SA (mirrors `profiles.yml` `prod-impersonate`); CI uses ADC
  directly (`OBS_IMPERSONATE=false` / `--no-impersonate`) because the runner is already
  `dbt-prod` via WIF. Defaults live in `config.py` as **functions** (read env after
  `.env` load), never import-time constants. Never add a write path or a keyfile.
- **Templates resolve package-relative** (`Path(__file__).parent / "assets"`), never
  cwd-relative — so the bundle resolves from source *and* when installed via `uvx`.
- **Brand + two-surface theming.** `design-tokens.json` holds a `brands` map (3 packs),
  each with `fonts` + `themes.{light,dark}`, each theme carrying a `chrome` palette, a
  `plotly` palette, and `gantt` colours. `applyBrandTheme` **injects** the chrome onto CSS
  variables at runtime (the static `:root[data-theme]` block in `obs.html` is only a
  first-paint fallback) AND re-renders the live canvas (Plotly `react` / Gantt redraw) —
  Plotly + the SVG Gantt can't read CSS vars, so it MUST do both, not just flip the
  attribute. `resourceColours`/`statusColours` are shared (data encodings, not brand).
  `design-tokens.json` is the single curate point (`FALLBACK_TOKENS` in the JS is a
  soft-fail default only); `write_bundle` copies it verbatim. Default brand/theme come from
  `defaultBrand`/`defaultTheme`; both persist in `localStorage`.
- **URL is the router.** `?run=<id>` ⇒ detail, absent ⇒ overview. `navigate()` pushes
  state then renders; `popstate` re-renders from the URL. Deep links and Back/Forward
  MUST keep working — the e2e suite asserts it. The overview Plotly scatter uses SVG
  (`type:"scatter"`, not `scattergl`) so its points are addressable by the e2e tests.
- **CLI shape:** `typer` app (`app = typer.Typer(...)` in `app.py`). `@app.command()`
  decorators register `generate`/`serve`; an `@app.callback()` runs the logging +
  repo-root + `.env` bootstrap before any command; `no_args_is_help=True` replaces the
  old `_help` closure. Shared flags are module-level `Annotated[...]` option aliases.
  `pretty_exceptions_enable=False` so the three fail-loud exceptions reach `main()`,
  which renders `❌ <msg>` + exit 1 (the same UX the argparse `main()` gave). NOTE: this
  deviates from `.claude/rules/python/cli.md` ("stdlib argparse only; do not introduce
  typer") — the deviation is scoped to `obs` and must be ratified there (or reverted)
  before other CLIs follow; sibling `adaf` is still argparse.
- **Output discipline:** human + log lines → stderr (`logging`); stdout stays clean
  for any future `--json`.

## Extension checklist

- [ ] Adding a new viewer feature (e.g. freshness timeline)? Read its Elementary
      table(s) in `elementary.py`, add a pure `build_<x>_payload` + a `write_bundle`-style
      writer, ship its `assets/` template, and wire a handler as a `@app.command()` (or a
      sub-app module, see next item). Unit-test the transform against a seeded fixture (no
      warehouse); add e2e coverage if it has UI.
- [ ] Second feature ⇒ split each feature into its own `typer.Typer()` sub-app and
      mount them with `app.add_typer(gantt_app, name="gantt")` etc. (`obs gantt generate`,
      `obs <new> generate`), so `app.py` stays wiring-only.
- [ ] New `dbt_run_results` field in the payload? Update the schema docstring in
      `gantt.py`, the JS consumer, AND the fixture + tests in the same change.
- [ ] Changed a default project/dataset/SA? It belongs in `config.py` as an
      env-overridable function, and the README table must match.
- [ ] Touched routing, theming, or the overview scatter? Run `make test-e2e` — the
      Playwright suite (`e2e/`) asserts deep links, Back/Forward, theme flip, mark-click
      navigation, and sidebar collapse against the served static SPA.

## Dev contract

Run from the repo root (never `cd`):

```bash
make -C .github/cli/obs ci         # lint + typecheck + unit tests (no warehouse, no browser)
make -C .github/cli/obs fix        # format + ruff --fix
make -C .github/cli/obs test-e2e   # Playwright e2e over the generated SPA (installs chromium; needs net)
uv run --directory .github/cli/obs obs serve   # live viewer (needs ADC + SA tokenCreator)
```
