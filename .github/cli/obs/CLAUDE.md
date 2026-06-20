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
`assets/gantt.js` (vanilla SVG, no build step). This is the same split as `adaf`'s
sdag viewer — and it's what keeps `make ci` free: the transforms are unit-tested
against a seeded fixture with **no warehouse**, only `generate`/`serve` touch BigQuery.

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
- **Design tokens are the single brand curate point.** `assets/design-tokens.json`
  owns every viewer colour (light + dark palettes, resource/status scales) and font.
  `gantt.js` reads it at runtime and projects each theme onto CSS variables — do NOT
  hardcode a second palette in the JS (the `FALLBACK_TOKENS` object is a soft-fail
  default only). `write_bundle` copies the file verbatim so editing it curates the viewer.
- **CLI shape:** stdlib `argparse` only; `_help` closure as each parser's default
  `func`; leaves override via `set_defaults`; `main()` dispatches `args.func(args)`
  and exits with its returned code (`.claude/rules/python/cli.md`).
- **Output discipline:** human + log lines → stderr (`logging`); stdout stays clean
  for any future `--json`.

## Extension checklist

- [ ] Adding a new viewer feature (e.g. freshness timeline)? Read its Elementary
      table(s) in `elementary.py`, add a pure `build_<x>_payload` + `write_outputs`
      pair, ship `assets/<x>.html` + `<x>.js`, and a `commands/<x>.py` handler. Unit-test
      the transform against a seeded fixture (no warehouse).
- [ ] Second feature ⇒ promote `generate`/`serve` into a per-feature group
      (`obs gantt generate`, `obs <new> generate`), mirroring `adaf products generate/serve`.
      Keep `app.py` logic-free.
- [ ] New `dbt_run_results` field in the payload? Update the schema docstring in
      `gantt.py`, the JS consumer, AND the fixture + tests in the same change.
- [ ] Changed a default project/dataset/SA? It belongs in `config.py` as an
      env-overridable function, and the README table must match.

## Dev contract

Run from the repo root (never `cd`):

```bash
make -C .github/cli/obs ci         # lint + typecheck + test (no warehouse)
make -C .github/cli/obs fix        # format + ruff --fix
uv run --directory .github/cli/obs obs serve   # live viewer (needs ADC + SA tokenCreator)
```
