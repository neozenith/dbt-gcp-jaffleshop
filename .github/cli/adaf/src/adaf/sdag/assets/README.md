# sdag viewer assets

The files the `adaf sdag generate` / `adaf sdag serve` viewer is built from.
Everything here is a *template* or *static asset* copied (some token-substituted)
into the output dir by `viewer.py`.

| File | What it is |
|------|------------|
| `sdag.html` | Page shell + chrome theming. CSS variables under `[data-theme]` theme the **HTML chrome** (sidebar, panels, badges). Templated: `{{BUILD_ID}}`. |
| `sdag.js` | Viewer logic. Reads `design-tokens.json` at runtime and builds the **canvas** palette/fonts from it. Templated: `{{BUILD_ID}}`, `{{SOURCE}}`. |
| `design-tokens.json` | **The brand aesthetic for the Cytoscape canvas.** Source of truth for `RESOURCE_COLOURS`, `THEMES`, the RAG (Red-Amber-Green) thresholds and the canvas fonts. Shipped verbatim (not templated). |

## Why two palettes (chrome vs canvas)

Cytoscape cannot read the CSS custom properties that theme the HTML chrome, so
the **canvas** carries its own parallel palette. The chrome palette lives in
`sdag.html` (`:root[data-theme=…]` CSS variables); the canvas palette lives in
`design-tokens.json`. They are kept in sync by hand — change one, eyeball the
other. This file documents the **canvas** tokens.

## Token schema (`design-tokens.json`)

```jsonc
{
  "version": 1,
  "resourceColours": { "model": "#3b82f6", ... },   // resource_type FILLS (not themed)
  "fonts": {
    "mono": "ui-monospace, monospace",              // canvas label font-family
    "sizes": { "node": 9, "test": 7, "compound": 11, "super": 15, "superEdge": 16 }
  },
  "rag": { "thresholds": { "ok": 80, "warn": 50 } }, // compliance % buckets
  "themes": { "dark": { ... }, "light": { ... } }    // per-theme canvas palette
}
```

### `resourceColours` — node fills by `resource_type`

Saturated mid-tones chosen to stay legible on **both** the dark and light
canvas, so they are deliberately **not** themed (only the chrome around a node
flips with the theme). One key per dbt resource type
(`model` / `test` / `seed` / `snapshot` / `source` / `analysis` / `exposure` /
`metric`); an unknown type falls back to a neutral slate in `viewer.py`. Mirrors
`NODE_COLOURS` in `viewer.py` (the JSON's per-node `colour` hint), so keep the
two in step.

### `fonts` — canvas typography

`mono` is the font-family applied to canvas node/super labels (the chrome uses
Poppins; the canvas uses a monospace stack for unique-id legibility). `sizes`
are the per-element label point sizes used by `buildStyle()` in `sdag.js`.
(Node/super *geometry* — widths, heights, padding — stays as layout in
`buildStyle()`; only brand-level type tokens live here.)

### `rag` — Red-Amber-Green compliance thresholds

The compliance-percentage cut-points shared by `pctClass`, `barColourVar`
(panel text/bars) and `superHealthState` (super-node health ring):

| Bucket | Condition | Meaning |
|--------|-----------|---------|
| ok | `pct >= ok` (80) | compliant / green |
| warn | `pct >= warn` (50) | at risk / amber |
| fail | below `warn` | failing / red |

A super-node with **no** cached compliance data is `nodata` (a calm dashed slate
ring) — never green, so a missing score can't read as a pass. The RAG *ring
colours* are theme-specific and live in each theme block (`superRag*`,
`compliance*Ring`, `complianceGlow`) — see below.

### `themes.{dark,light}` — the per-theme canvas palette

Every key is a colour (hex) except `name`, `toggleLabel`, and
`compoundBgOpacity` (0–1). The groups:

| Keys | Theme |
|------|-------|
| `nodeOutline`, `nodeLabel`, `nodeLabelOutline` | leaf node outline + label |
| `compound*` | selector compound boxes (matched + `*Unmatched`) |
| `super*` | collapsed super-nodes (matched + `*Unmatched`) |
| `edge`, `superEdge*` | lineage edges + aggregated super edges + their count labels |
| `selected` | tap-selection highlight (brand lime / olive) |
| `boundaryInbound/Outbound/Both` (`{bg,border}`) | filtered-view boundary annotations |
| `haloUpstream/Downstream` (`{bg,border}`), `haloEdge`, `haloCompound*` | filtered-view external context halo |
| `compliancePassRing`, `complianceFailRing`, `complianceGlow` | per-node compliance rings (T20) |
| `superRagOk/Warn/Fail`, `superRagFailGlow`, `superRagNeutral` | super-node health rings (T33) |

The dark theme is anchored on the slate (`#242C30` / `#3A474E`) with the
brand lime (`#A5C84D`) accent; the light theme uses white/grey chrome with the
darker olive (`#6E8F26`) accent so accents stay AA on white. See
`adaf/docs/design.md` for the brand-token provenance.

## How the viewer loads it

1. `sdag.js` declares `FALLBACK_TOKENS` (a copy of these values) and binds
   `RESOURCE_COLOURS` / `THEMES` / `RAG_THRESHOLDS` / `FONTS` to it.
2. On `DOMContentLoaded`, **before first paint**, `loadTokens()` runs:
   - if `window.__SDAG_TOKENS__` is present (the `--inline` standalone build),
     it uses that;
   - else it `fetch`es `design-tokens.json?v=<build-id>` (same cache-bust as the
     graph JSON);
   - on a genuine load failure it logs `console.error(...)` and keeps the
     built-in `FALLBACK_TOKENS` so the viewer still renders.
3. The fetched tokens replace the live bindings; `applyTheme()` + `buildStyle()`
   then build the Cytoscape stylesheet from them. A theme toggle just re-runs
   `buildStyle()` against the other theme — no refetch.

`viewer.py` ships the file: `write_outputs()` copies it next to the other assets
(served by `adaf sdag serve`), and `write_inline()` embeds it on
`window.__SDAG_TOKENS__` so the standalone single-file HTML needs no sidecar.

## Configuring / overriding

- **Tweak a colour, font size or threshold:** edit `design-tokens.json` and
  reload the served page (the fetch is `no-store`; `serve` regenerates first).
  No JS change needed. Keep `FALLBACK_TOKENS` in `sdag.js` in step if the change
  is meant to be the permanent default (it is the offline safety net).
- **Add a theme:** add a third key under `themes` (e.g. `"highContrast"`) with
  the full key set above, then extend the theme toggle in `sdag.js`
  (`toggleTheme` currently flips dark↔light) and the `[data-theme]` block in
  `sdag.html` to match. Every new theme must supply *all* keys — there is no
  per-key inheritance.
- **Add a resource type colour:** add a key to `resourceColours` and the
  matching `NODE_COLOURS` entry in `viewer.py`.

## WCAG AA expectation

Both `dark` and `light` themes are tuned so node/edge labels and the
compliance/RAG rings meet **WCAG AA (≥ 4.5:1 contrast)** against the
backgrounds they sit on in that theme — e.g. the dark RAG rings are bright tints
that read on the dark super-node fill **and** the dark canvas, while the light
theme drops the lime accent to a darker olive so it stays AA on white. When you
change any theme colour, re-check the affected text/ring against its background
(4.5:1 minimum) before committing — do not regress either theme below AA.
