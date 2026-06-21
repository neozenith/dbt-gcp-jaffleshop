// sdag.js — viewer logic for the super-DAG.
//
// Templated by `sdag.py write_outputs()` at build time:
//   {{BUILD_ID}}  → timestamp of the generate run (cache-bust + banner)
//   {{SOURCE}}    → dbt target/ path the manifest was read from
// If you ever load this file directly without templating, both will appear
// literally as `{{...}}` — that's the signal that the build step was skipped.

// ─────────────────────────────────────────────────────────────────────────
// Design tokens — the aesthetic for the CANVAS lives in
// design-tokens.json, fetched at runtime (like the graph JSON) and turned into
// RESOURCE_COLOURS, THEMES, the RAG thresholds and the canvas fonts below. The
// JSON is the SOURCE OF TRUTH; the FALLBACK_TOKENS literals are a built-in
// safety net used ONLY when the fetch genuinely fails (a console.error is
// surfaced when that happens) so the viewer still renders rather than throwing.
//
// Why a parallel palette at all: Cytoscape can't read the CSS variables that
// theme the HTML chrome (sdag.html), so the canvas carries its own palette.
// The two are kept in sync by hand. buildStyle() turns the active theme into a
// Cytoscape stylesheet; a theme switch rebuilds + re-applies it live.
//
// Palette notes carried over from the old hard-coded values:
//   • RESOURCE_COLOURS are resource_type FILLS — saturated mid-tones legible on
//     BOTH canvases, so (unlike the chrome) they are NOT themed; only outlines/
//     labels/edges and compound/super boxes flip with the theme.
//   • Both THEMES palettes are tuned so node/edge labels and the compliance/RAG
//     rings meet WCAG AA against their backgrounds in their respective theme.
// See assets/README.md for the schema, the WCAG AA expectation, and how to
// override or add a theme.
// ─────────────────────────────────────────────────────────────────────────
const FALLBACK_TOKENS = {
  resourceColours: {
    model:    "#3b82f6",
    test:     "#a855f7",
    seed:     "#10b981",
    snapshot: "#f59e0b",
    source:   "#6b7280",
    analysis: "#ec4899",
    exposure: "#ef4444",
    metric:   "#14b8a6",
  },
  fonts: {
    mono: "ui-monospace, monospace",
    sizes: { node: 9, test: 7, compound: 11, super: 15, superEdge: 16 },
  },
  rag: { thresholds: { ok: 80, warn: 50 } },
  themes: {
    dark: {
      name: "dark", toggleLabel: "☽ Dark",
      nodeOutline: "#242C30",
      nodeLabel: "#ffffff", nodeLabelOutline: "#242C30",
      compoundBg: "#2D373D", compoundBgOpacity: 0.35,
      compoundBorder: "#A5C84D", compoundLabel: "#ffffff", compoundLabelOutline: "#242C30",
      compoundUnmatchedBorder: "#4B5C65", compoundUnmatchedLabel: "#9AA4A8",
      superBg: "#3A474E", superBorder: "#A5C84D", superLabel: "#ffffff", superLabelOutline: "#242C30",
      superUnmatchedBg: "#46555D", superUnmatchedBorder: "#2D373D",
      edge: "#6B7C85",
      superEdge: "#A5C84D", superEdgeLabel: "#C4DD7F", superEdgeLabelBg: "#242C30",
      selected: "#A5C84D",
      boundaryInbound:  { bg: "#10b981", border: "#6ee7b7" },
      boundaryOutbound: { bg: "#f59e0b", border: "#fcd34d" },
      boundaryBoth:     { bg: "#f43f5e", border: "#fb7185" },
      haloUpstream:   { bg: "#334155", border: "#64748b" },
      haloDownstream: { bg: "#3b3651", border: "#6b5fa3" },
      haloEdge: "#64748b",
      haloCompoundBorder: "#475569", haloCompoundLabel: "#94a3b8",
      complianceFailRing: "#fca5a5", compliancePassRing: "#86efac",
      complianceGlow: "#ef4444",
      superRagOk: "#6ee7b7", superRagWarn: "#fcd34d", superRagFail: "#fca5a5",
      superRagFailGlow: "#ef4444", superRagNeutral: "#8896a0",
    },
    light: {
      name: "light", toggleLabel: "☼ Light",
      nodeOutline: "#FFFFFF",
      nodeLabel: "#ffffff", nodeLabelOutline: "#1B2125",
      compoundBg: "#FFFFFF", compoundBgOpacity: 0.5,
      compoundBorder: "#6E8F26", compoundLabel: "#1B2125", compoundLabelOutline: "#FFFFFF",
      compoundUnmatchedBorder: "#C2C8CB", compoundUnmatchedLabel: "#56656D",
      superBg: "#4B5C65", superBorder: "#6E8F26", superLabel: "#ffffff", superLabelOutline: "#1B2125",
      superUnmatchedBg: "#9AA4A8", superUnmatchedBorder: "#C2C8CB",
      edge: "#8A99A1",
      superEdge: "#6E8F26", superEdgeLabel: "#3F560C", superEdgeLabelBg: "#FFFFFF",
      selected: "#6E8F26",
      boundaryInbound:  { bg: "#059669", border: "#065f46" },
      boundaryOutbound: { bg: "#d97706", border: "#92400e" },
      boundaryBoth:     { bg: "#e11d48", border: "#9f1239" },
      haloUpstream:   { bg: "#cbd5e1", border: "#64748b" },
      haloDownstream: { bg: "#d6ccf0", border: "#6b5fa3" },
      haloEdge: "#94a3b8",
      haloCompoundBorder: "#94a3b8", haloCompoundLabel: "#56656D",
      complianceFailRing: "#991b1b", compliancePassRing: "#166534",
      complianceGlow: "#dc2626",
      superRagOk: "#34d399", superRagWarn: "#fbbf24", superRagFail: "#fb7185",
      superRagFailGlow: "#dc2626", superRagNeutral: "#b6c0c6",
    },
  },
};

// Live token bindings — replaced wholesale by loadTokens() before first paint.
// They default to the fallback so nothing throws if read before the load.
let RESOURCE_COLOURS = FALLBACK_TOKENS.resourceColours;
let THEMES = FALLBACK_TOKENS.themes;
let RAG_THRESHOLDS = FALLBACK_TOKENS.rag.thresholds;
let FONTS = FALLBACK_TOKENS.fonts;

const DESIGN_TOKENS_FILE = "design-tokens.json";

// Load the externalised design tokens. Prefers an inlined window.__SDAG_TOKENS__
// (standalone `--inline` build), else fetches design-tokens.json like the graph
// JSON. A genuine load failure logs a console error and falls back to the
// built-in literals — the JSON remains the source of truth, the fallback only
// keeps the viewer alive.
async function loadTokens() {
  let tokens = null;
  if (typeof window !== "undefined" && window.__SDAG_TOKENS__) {
    tokens = window.__SDAG_TOKENS__;
  } else {
    try {
      const r = await fetch(`${DESIGN_TOKENS_FILE}?v=${encodeURIComponent(BUILD_ID)}`, { cache: "no-store" });
      if (!r.ok) throw new Error(`${DESIGN_TOKENS_FILE}: ${r.status} ${r.statusText}`);
      tokens = await r.json();
    } catch (e) {
      console.error(`sdag: failed to load ${DESIGN_TOKENS_FILE}; using built-in fallback design tokens.`, e);
      tokens = FALLBACK_TOKENS;
    }
  }
  RESOURCE_COLOURS = tokens.resourceColours || FALLBACK_TOKENS.resourceColours;
  THEMES = tokens.themes || FALLBACK_TOKENS.themes;
  RAG_THRESHOLDS = (tokens.rag && tokens.rag.thresholds) || FALLBACK_TOKENS.rag.thresholds;
  FONTS = tokens.fonts || FALLBACK_TOKENS.fonts;
}

const THEME_KEY = "sdag-theme";
// Resolved by the inline bootstrap in sdag.html before this script runs.
let currentTheme = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";

// ─────────────────────────────────────────────────────────────────────────
// Build identity — substituted at write-time by sdag.py write_outputs().
// Used as a cache-bust query-string on the JSON fetches so the browser
// can't serve stale data across regenerations of the same output dir.
// ─────────────────────────────────────────────────────────────────────────
const BUILD_ID = "{{BUILD_ID}}";
const SOURCE   = "{{SOURCE}}";

// ─────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────
let cy = null;
let currentView = "full";  // "full" | "super"
let currentFilter = "__all__";  // "__all__" | <selector name from the dropdown>
const cache = { full: null, super: null };

// Nodes re-homed under the active selector's compound for the filter's duration
// (see applyFilter()). Each entry is { node, parent } where `parent` is the id
// the node was parented to BEFORE the move, so the next applyFilter() can put it
// back. Cleared whenever the cy instance is destroyed (the refs go stale).
let rehomedNodes = [];

// ─────────────────────────────────────────────────────────────────────────
// URL state sync — deep-linkable view + filter with Back/Forward support.
//
//   ?view=full|super     which view is showing
//   ?selector=<name>     active full-graph filter (omitted when "(show all)")
// ─────────────────────────────────────────────────────────────────────────
const URL_PARAM_VIEW = "view";
const URL_PARAM_SELECTOR = "selector";

// Set while we're applying state pulled FROM the URL (popstate) so the
// downstream showView()/applyFilter() renders don't write the URL back.
let suppressUrlSync = false;

function readUrlState() {
  const params = new URLSearchParams(window.location.search);
  const view = params.get(URL_PARAM_VIEW);
  const selector = params.get(URL_PARAM_SELECTOR);
  return {
    view: view === "full" || view === "super" ? view : null,
    selector: selector || null,
  };
}

function canonicalUrl() {
  const params = new URLSearchParams(window.location.search);
  params.set(URL_PARAM_VIEW, currentView);
  if (currentFilter && currentFilter !== "__all__") {
    params.set(URL_PARAM_SELECTOR, currentFilter);
  } else {
    params.delete(URL_PARAM_SELECTOR);
  }
  const qs = params.toString();
  return `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`;
}

function currentUrl() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function syncUrl() {
  if (suppressUrlSync) return;          // applying state from Back/Forward
  const next = canonicalUrl();
  if (next === currentUrl()) return;    // no-op: don't spam the history stack
  window.history.pushState(null, "", next);
}

function applyStateFromUrl() {
  const urlState = readUrlState();
  const select = document.getElementById("filter-selector");
  const valid =
    urlState.selector &&
    Array.from(select.options).some((o) => o.value === urlState.selector);
  currentFilter = valid ? urlState.selector : "__all__";
  select.value = currentFilter;
  setFilterLegendVisible(currentFilter !== "__all__");
  return urlState.view || (currentFilter !== "__all__" ? "full" : "super");
}

// ─────────────────────────────────────────────────────────────────────────
// Cytoscape stylesheet — built from the active theme (class-driven, shared by
// both views). A theme switch calls buildStyle() again and cy.style()s it in.
// ─────────────────────────────────────────────────────────────────────────
function buildStyle(t) {
  return [
    // Default leaf entity node. Labels are pure white with a theme outline so
    // they stay legible across every resource_type colour AND on both canvases.
    {
      selector: "node",
      style: {
        "background-color": "data(colour)",
        "border-width": 1,
        "border-color": t.nodeOutline,
        "label": "data(label)",
        "color": t.nodeLabel,
        "font-size": FONTS.sizes.node,
        "font-weight": 600,
        "font-family": FONTS.mono,
        "text-valign": "center",
        "text-halign": "center",
        "text-outline-color": t.nodeLabelOutline,
        "text-outline-width": 1.5,
        "text-max-width": 80,
        "text-wrap": "ellipsis",
        "width": 18,
        "height": 18,
      },
    },

    // Per-resource_type sizing tweaks
    { selector: "node.entity-model",    style: { width: 22, height: 22 } },
    { selector: "node.entity-test",     style: { width: 12, height: 12, "font-size": FONTS.sizes.test } },
    { selector: "node.entity-source",   style: { shape: "round-rectangle", width: 26, height: 16 } },
    { selector: "node.entity-snapshot", style: { shape: "diamond", width: 20, height: 20 } },
    { selector: "node.entity-seed",     style: { shape: "round-pentagon", width: 18, height: 18 } },

    // Compound (selector) parent nodes
    {
      selector: "node.selector-compound",
      style: {
        "background-color": t.compoundBg,
        "background-opacity": t.compoundBgOpacity,
        "border-color": t.compoundBorder,
        "border-width": 1,
        "label": "data(label)",
        "color": t.compoundLabel,
        "text-outline-color": t.compoundLabelOutline,
        "text-outline-width": 1.5,
        "text-valign": "top",
        "text-halign": "left",
        "font-size": FONTS.sizes.compound,
        "font-weight": 600,
        "padding": 16,
        "shape": "round-rectangle",
      },
    },
    {
      selector: "node.selector-compound.unmatched",
      style: { "border-color": t.compoundUnmatchedBorder, "color": t.compoundUnmatchedLabel },
    },

    // Super nodes (collapsed-selector view) — sized by member count. The label
    // is a multi-line product health summary (T33): name + compliance + a
    // governance roll-up, so font-size drops from the single-line original and
    // the min size grows to keep all three lines legible on the smallest node.
    {
      selector: "node.super",
      style: {
        "background-color": t.superBg,
        "background-opacity": 0.95,
        "border-color": t.superBorder,
        "border-width": 2,
        "shape": "round-rectangle",
        "label": "data(label)",
        "color": t.superLabel,
        "font-size": FONTS.sizes.super,
        "font-weight": 700,
        "font-family": FONTS.mono,
        "padding": 14,
        "text-valign": "center",
        "text-halign": "center",
        "text-wrap": "wrap",
        "text-max-width": 250,
        "text-outline-color": t.superLabelOutline,
        "text-outline-width": 3,
        "line-height": 1.25,
        "width": "mapData(log_members, 0, 8, 160, 380)",
        "height": "mapData(log_members, 0, 8, 96, 250)",
      },
    },
    {
      selector: "node.super.unmatched",
      style: { "background-color": t.superUnmatchedBg, "border-color": t.superUnmatchedBorder },
    },

    // ── Super-node health rings (T33) — RAG by the product's compliance %,
    // mirroring T20's thresholds (>=80 ok, >=50 warn, else fail). A FAILED
    // product gets the thick ring + red underlay glow (same language as the
    // per-node compliance-fail ring); an UNGRADED product (no compliance data
    // in the cache) gets a calm dashed slate ring — never green, so a missing
    // score can't read as a pass.
    { selector: 'node.super[health = "ok"]',   style: { "border-color": t.superRagOk,   "border-width": 5 } },
    { selector: 'node.super[health = "warn"]', style: { "border-color": t.superRagWarn, "border-width": 5 } },
    { selector: 'node.super[health = "fail"]', style: {
        "border-color": t.superRagFail, "border-width": 6,
        "underlay-color": t.superRagFailGlow, "underlay-opacity": 0.30, "underlay-padding": 10,
      } },
    { selector: 'node.super[health = "nodata"]', style: {
        "border-color": t.superRagNeutral, "border-width": 3, "border-style": "dashed",
      } },

    // Lineage edges in the full view
    {
      selector: "edge.edge-lineage",
      style: {
        "width": 1,
        "line-color": t.edge,
        "curve-style": "bezier",
        "target-arrow-shape": "triangle",
        "target-arrow-color": t.edge,
        "arrow-scale": 0.6,
        "opacity": 0.6,
      },
    },

    // Aggregated edges in the super view — width scales with log1p(count).
    {
      selector: "edge[count]",
      style: {
        "width": "mapData(log_count, 0, 6.5, 1.5, 14)",
        "line-color": t.superEdge,
        "target-arrow-color": t.superEdge,
        "curve-style": "bezier",
        "target-arrow-shape": "triangle",
        "label": "data(count)",
        "color": t.superEdgeLabel,
        "font-size": FONTS.sizes.superEdge,
        "font-weight": 700,
        "text-background-color": t.superEdgeLabelBg,
        "text-background-opacity": 0.9,
        "text-background-padding": 3,
        "opacity": 0.85,
      },
    },

    // ── Filtered-view boundary annotations ───────────────────────────────
    { selector: "node.boundary-inbound", style: {
        "background-color": t.boundaryInbound.bg, "border-color": t.boundaryInbound.border, "border-width": 3,
      } },
    { selector: "node.boundary-outbound", style: {
        "background-color": t.boundaryOutbound.bg, "border-color": t.boundaryOutbound.border, "border-width": 3,
      } },
    { selector: "node.boundary-both", style: {
        "background-color": t.boundaryBoth.bg, "border-color": t.boundaryBoth.border, "border-width": 3,
      } },
    { selector: "node.halo-upstream", style: {
        "background-color": t.haloUpstream.bg, "border-color": t.haloUpstream.border, "opacity": 0.75,
      } },
    { selector: "node.halo-downstream", style: {
        "background-color": t.haloDownstream.bg, "border-color": t.haloDownstream.border, "opacity": 0.75,
      } },
    { selector: "edge.halo-edge", style: {
        "line-color": t.haloEdge, "target-arrow-color": t.haloEdge, "line-style": "dashed", "opacity": 0.6,
      } },
    { selector: "node.selector-compound.halo-compound", style: {
        "border-color": t.haloCompoundBorder, "border-style": "dashed",
        "background-opacity": 0.15, "color": t.haloCompoundLabel,
      } },

    // ── Compliance rings (T20) — applied over boundary nodes when a selector
    // filter is active. A FAILED boundary obligation gets a thick ring + a red
    // underlay glow so it's unmissable; a fully-satisfied boundary node gets a
    // calmer pass ring.
    { selector: "node.compliance-pass", style: {
        "border-color": t.compliancePassRing, "border-width": 3,
      } },
    { selector: "node.compliance-fail", style: {
        "border-color": t.complianceFailRing, "border-width": 5,
        "underlay-color": t.complianceGlow, "underlay-opacity": 0.35, "underlay-padding": 8,
      } },

    // Selection highlight (kept LAST so it overrides boundary/compliance
    // borders when the user has explicitly tapped a node).
    { selector: ":selected", style: { "border-color": t.selected, "border-width": 4 } },
  ];
}

// ─────────────────────────────────────────────────────────────────────────
// Theme provider (T22)
// ─────────────────────────────────────────────────────────────────────────
function applyTheme(theme, { persist = true } = {}) {
  currentTheme = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", currentTheme);
  if (persist) {
    try { localStorage.setItem(THEME_KEY, currentTheme); } catch (e) { /* private mode */ }
  }
  const btn = document.getElementById("btn-theme");
  if (btn) btn.textContent = THEMES[currentTheme].toggleLabel;
  // Restyle the live graph (classes persist; only the stylesheet changes).
  if (cy) cy.style(buildStyle(THEMES[currentTheme]));
}

function toggleTheme() {
  applyTheme(currentTheme === "dark" ? "light" : "dark");
}

// ─────────────────────────────────────────────────────────────────────────
// Layout config — Dagre per requirements.
// ─────────────────────────────────────────────────────────────────────────
const LAYOUTS = {
  full: {
    name: "dagre", rankDir: "LR", nodeSep: 14, rankSep: 80, edgeSep: 4,
    ranker: "tight-tree", acyclicer: "greedy", animate: false, fit: false, padding: 30,
  },
  super: {
    name: "dagre", rankDir: "LR", nodeSep: 14, rankSep: 70,
    ranker: "tight-tree", acyclicer: "greedy", animate: false, fit: false, padding: 30,
  },
};
const FALLBACK_LAYOUT = {
  name: "cose", animate: false, fit: false, padding: 30,
  idealEdgeLength: 80, nodeRepulsion: 6000, gravity: 0.4,
};
const MIN_VIEW_ZOOM = 0.45;  // floor at which super-node labels stay legible

// ─────────────────────────────────────────────────────────────────────────
// Data loading
// ─────────────────────────────────────────────────────────────────────────
async function fetchView(name) {
  if (cache[name]) return cache[name];
  if (typeof window !== "undefined" && window.__SDAG_DATA__ && window.__SDAG_DATA__[name]) {
    cache[name] = window.__SDAG_DATA__[name];
    return cache[name];
  }
  const file = name === "full" ? "full_graph.json" : "super_graph.json";
  const status = document.getElementById("status");
  status.textContent = `loading ${file}…`;
  const r = await fetch(`${file}?v=${encodeURIComponent(BUILD_ID)}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${file}: ${r.status} ${r.statusText}`);
  const data = await r.json();
  cache[name] = data;
  return data;
}

// ─────────────────────────────────────────────────────────────────────────
// Compliance (T20) — per-selector rollup + per-node annotations, embedded in
// full_graph.json metadata.compliance by viewer.py (read straight from the
// cache files that `adaf sdag check` enriches).
// ─────────────────────────────────────────────────────────────────────────
function complianceMap() {
  return (cache.full && cache.full.metadata && cache.full.metadata.compliance) || {};
}

function complianceFor(selector) {
  const m = complianceMap();
  return m[selector] || null;
}

// uid → short display label, from the full graph's entity elements.
let _labelOf = null;
function labelOf(uid) {
  if (!_labelOf) {
    _labelOf = new Map();
    const els = (cache.full && cache.full.elements) || [];
    for (const e of els) {
      if (e.data && e.data.kind === "entity") _labelOf.set(e.data.id, e.data.label || e.data.id);
    }
  }
  return _labelOf.get(uid) || uid.split(".").pop();
}

function failingRuleIds(annEntry) {
  return (annEntry.rules || []).filter((r) => r.status === "fail").map((r) => r.rule_id);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function pctClass(pct) {
  if (pct >= RAG_THRESHOLDS.ok) return "pct-ok";
  if (pct >= RAG_THRESHOLDS.warn) return "pct-warn";
  return "pct-fail";
}
function barColourVar(pct) {
  if (pct >= RAG_THRESHOLDS.ok) return "var(--ok-text)";
  if (pct >= RAG_THRESHOLDS.warn) return "var(--warn-text)";
  return "var(--fail-text)";
}

// ─────────────────────────────────────────────────────────────────────────
// Super-node product health summary (T33) — a SUMMARISED version of the
// per-node governance/compliance visuals, stamped onto each collapsed super
// node so a reviewer reads each data product's health WITHOUT expanding it.
//
// Sourced entirely from the already-loaded FULL graph (no extra fetch, no
// viewer.py change needed):
//   • compliance % + fails ← cache.full.metadata.compliance[selector]
//   • governance roll-up    ← aggregated across the product's entity nodes,
//                             reusing the per-node fields T21 stamped.
// ─────────────────────────────────────────────────────────────────────────

// RAG bucket for a compliance %, matching T20's pctClass thresholds.
function superHealthState(pct) {
  if (pct >= RAG_THRESHOLDS.ok) return "ok";
  if (pct >= RAG_THRESHOLDS.warn) return "warn";
  return "fail";
}

// Aggregate documented / tested / semantic-backed counts across a product's
// governable data nodes. Tests are excluded from the denominator — a test
// having "no description / no tests" would only dilute the coverage signal.
function governanceRollup(selector) {
  const els = (cache.full && cache.full.elements) || [];
  let total = 0, documented = 0, tested = 0, semantic = 0;
  for (const e of els) {
    const d = e.data;
    if (!d || d.kind !== "entity") continue;
    if (d.resource_type === "test") continue;
    if (!(d.selectors || []).includes(selector)) continue;
    total += 1;
    if (d.has_description) documented += 1;
    if ((d.test_count || 0) > 0) tested += 1;
    if (d.semantic_backed) semantic += 1;
  }
  return { total, documented, tested, semantic };
}

// Compliance summary for a product, or null when the cache carries no
// compliance data for it (an UNGRADED product — never fabricate a score).
function superComplianceSummary(selector) {
  const entry = complianceFor(selector);
  const c = entry && entry.compliance;
  if (!c || typeof c.compliance_pct !== "number") return null;
  return { pct: c.compliance_pct, failed: c.failed || 0, total: c.total || 0 };
}

// Decorate every super node in `superData` with its health summary: a
// multi-line label and a `health` data attr the stylesheet rings off. Mutates
// the cached payload in place; the guard keeps it idempotent across re-renders.
function decorateSuperNodes(superData) {
  for (const e of (superData.elements || [])) {
    const d = e.data;
    if (!d || d.kind !== "super") continue;
    if (d._healthApplied) { continue; }
    if (d.base_label === undefined) d.base_label = d.label;

    const comp = superComplianceSummary(d.id);
    const gov = governanceRollup(d.id);

    const lines = [d.base_label];
    if (comp) {
      lines.push(`${comp.pct}% · ${comp.failed} fail${comp.failed === 1 ? "" : "s"}`);
    } else {
      lines.push("ungraded · no data");
    }
    if (gov.total) {
      lines.push(`doc ${gov.documented}/${gov.total} · test ${gov.tested}/${gov.total} · sem ${gov.semantic}/${gov.total}`);
    }
    d.label = lines.join("\n");
    d.health = comp ? superHealthState(comp.pct) : "nodata";
    d.compliance_pct = comp ? comp.pct : null;
    d._healthApplied = true;
  }
}

// HTML summary card for the super-node selection panel (T33) — the SUMMARISED
// per-node detail visuals (the praised badges) rolled up to product level.
function superSummaryHtml(selector) {
  const comp = superComplianceSummary(selector);
  const gov = governanceRollup(selector);
  const parts = [];
  parts.push(`<div class="compliance-card mb-2">`);
  if (comp) {
    parts.push(
      `<div class="flex items-baseline gap-2">` +
        `<span class="compliance-pct ${pctClass(comp.pct)}">${comp.pct}%</span>` +
        `<span class="text-sub text-xs">compliant</span>` +
      `</div>`,
    );
    parts.push(`<div class="compliance-bar"><span style="width:${Math.max(0, Math.min(100, comp.pct))}%;background:${barColourVar(comp.pct)}"></span></div>`);
    parts.push(
      `<div class="text-sub text-[11px]">` +
        `<span class="${comp.failed ? "pct-fail" : "pct-ok"} font-semibold">${comp.failed}/${comp.total}</span> obligations failed` +
      `</div>`,
    );
  } else {
    parts.push(`<div class="text-sub text-xs">ungraded · no compliance data cached for this product</div>`);
  }
  if (gov.total) {
    const cov = (n) => {
      const cls = n === gov.total ? "badge-pass" : (n === 0 ? "badge-fail" : "badge-warn");
      return `<span class="badge ${cls}">${n}/${gov.total}</span>`;
    };
    parts.push(`<div class="divider mt-2 pt-2">`);
    parts.push(`<div class="text-label uppercase tracking-wider text-[10px] mb-1">Governance roll-up</div>`);
    parts.push(`<div class="gov-row">${cov(gov.documented)}<span class="text-body text-[11px]">documented</span></div>`);
    parts.push(`<div class="gov-row">${cov(gov.tested)}<span class="text-body text-[11px]">tested</span></div>`);
    parts.push(`<div class="gov-row">${cov(gov.semantic)}<span class="text-body text-[11px]">semantic-backed</span></div>`);
    parts.push(`</div>`);
  }
  parts.push(`</div>`);
  return parts.join("");
}

// Render the compliance panel for the active selector (or hide it). Shows the
// product rollup ("demand — 23% compliant, 10/13 obligations failed") plus a
// per failing-node list with the failing rule-id badges.
function renderCompliance(selector) {
  const panel = document.getElementById("compliance");
  if (!panel) return;
  const entry = (selector && selector !== "__all__") ? complianceFor(selector) : null;
  if (!entry) {
    panel.classList.remove("visible");
    panel.innerHTML = "";
    return;
  }
  const c = entry.compliance || {};
  const ann = entry.annotations || {};
  const total = c.total || 0;
  const failed = c.failed || 0;
  const pct = (typeof c.compliance_pct === "number") ? c.compliance_pct : (total ? Math.round(100 * (total - failed) / total) : 100);

  const failedNodes = [];
  for (const [uid, a] of Object.entries(ann)) {
    const ids = failingRuleIds(a);
    if (ids.length) failedNodes.push({ uid, boundary: a.boundary, ids });
  }
  failedNodes.sort((x, y) => labelOf(x.uid).localeCompare(labelOf(y.uid)));

  const parts = [];
  parts.push(`<div class="text-label uppercase tracking-wider mb-1 text-xs">Compliance</div>`);
  parts.push(`<div class="compliance-card">`);
  parts.push(
    `<div class="flex items-baseline gap-2">` +
      `<span class="compliance-pct ${pctClass(pct)}">${pct}%</span>` +
      `<span class="text-sub text-xs">compliant</span>` +
    `</div>`,
  );
  parts.push(`<div class="text-body text-xs mono mt-1">${escapeHtml(selector)}</div>`);
  parts.push(`<div class="compliance-bar"><span style="width:${Math.max(0, Math.min(100, pct))}%;background:${barColourVar(pct)}"></span></div>`);
  parts.push(
    `<div class="text-sub text-[11px]">` +
      `<span class="${failed ? "pct-fail" : "pct-ok"} font-semibold">${failed}/${total}</span> obligations failed` +
      ` · ${c.passed || 0} passed · ${c.suppressed || 0} suppressed` +
    `</div>`,
  );
  parts.push(
    `<div class="text-sub text-[11px] mt-0.5">` +
      `${c.boundary_nodes || 0} boundary nodes · <span class="${(c.failed_nodes ? "pct-fail" : "pct-ok")}">${c.failed_nodes || 0} failing</span>` +
    `</div>`,
  );

  if (failedNodes.length) {
    parts.push(`<div class="mt-2 pt-1">`);
    parts.push(`<div class="text-label uppercase tracking-wider text-[10px] mb-1">Failing obligations</div>`);
    for (const fn of failedNodes) {
      const badges = fn.ids.map((id) => `<span class="badge badge-fail">${escapeHtml(id)}</span>`).join(" ");
      parts.push(
        `<div class="failed-node-row py-1">` +
          `<div class="text-body text-[11px] mono">${escapeHtml(labelOf(fn.uid))} ` +
            `<span class="badge badge-soft">${escapeHtml(fn.boundary)}</span></div>` +
          `<div class="mt-0.5">${badges}</div>` +
        `</div>`,
      );
    }
    parts.push(`</div>`);
  } else {
    parts.push(`<div class="mt-2 text-[11px] pct-ok">All boundary obligations satisfied ✓</div>`);
  }
  parts.push(`</div>`);
  panel.innerHTML = parts.join("");
  panel.classList.add("visible");
}

// ─────────────────────────────────────────────────────────────────────────
// Rendering
// ─────────────────────────────────────────────────────────────────────────
async function showView(name) {
  currentView = name;
  document.getElementById("btn-full" ).classList.toggle("is-active", name === "full");
  document.getElementById("btn-super").classList.toggle("is-active", name === "super");

  const data = await fetchView(name);
  if (name === "full") populateFilterDropdown(data);
  // Stamp each collapsed super node with its product health summary (T33).
  // cache.full is always loaded first at boot, so the compliance + governance
  // source data is guaranteed present by the time the super view renders.
  if (name === "super") decorateSuperNodes(data);

  const status = document.getElementById("status");
  status.textContent = `rendering ${data.elements.length} elements…`;

  if (cy) { cy.destroy(); cy = null; rehomedNodes = []; }
  cy = cytoscape({
    container: document.getElementById("cy"),
    elements: data.elements,
    style: buildStyle(THEMES[currentTheme]),
    layout: { name: "preset" },
    wheelSensitivity: 0.2,
    minZoom: 0.05,
    maxZoom: 4,
  });
  window.cy = cy;  // debug handle (also lets headless checks inspect fit state)

  applyFilter();
  runLayout(name, status, data);

  cy.on("tap", "node", (evt) => {
    const d = evt.target.data();
    if (d.kind === "super") {
      renderBoundaryReport(buildBoundaryReport(d.id));
    } else {
      renderDetail(d);
    }
  });
  cy.on("tap", "edge", (evt) => renderDetail(evt.target.data()));
  cy.on("tap", (evt) => { if (evt.target === cy) clearDetail(); });

  // Governance hover tooltip (T21).
  cy.on("mouseover", "node.entity", (evt) => showTooltip(evt));
  cy.on("mousemove", "node.entity", (evt) => moveTooltip(evt));
  cy.on("mouseout", "node.entity", () => hideTooltip());
  // Super-node product-health tooltip (T40).
  cy.on("mouseover", "node.super", (evt) => showSuperTooltip(evt));
  cy.on("mousemove", "node.super", (evt) => moveTooltip(evt));
  cy.on("mouseout", "node.super", () => hideTooltip());
  cy.on("pan zoom drag", () => hideTooltip());

  renderMetadata(data.metadata, name);
  renderCompliance(currentView === "full" ? currentFilter : "__all__");
  syncUrl();
}

// ─────────────────────────────────────────────────────────────────────────
// Selector filter
// ─────────────────────────────────────────────────────────────────────────
function populateFilterDropdown(fullGraphData) {
  const select = document.getElementById("filter-selector");
  if (select.options.length > 1) return;
  const comp = (fullGraphData.metadata && fullGraphData.metadata.compliance) || {};
  const compounds = fullGraphData.elements
    .filter((e) => e.data && e.data.kind === "selector_compound")
    .map((e) => ({ name: e.data.selector, label: e.data.label, n: e.data.n_members }))
    .sort((a, b) => a.label.localeCompare(b.label));
  for (const c of compounds) {
    const opt = document.createElement("option");
    opt.value = c.name;
    // Flag products that carry compliance data with their score, so the
    // dropdown hints where the compliance panel will light up.
    const cc = comp[c.name];
    const tag = cc && cc.compliance && typeof cc.compliance.compliance_pct === "number"
      ? `  ·  ${cc.compliance.compliance_pct}%`
      : "";
    opt.textContent = `${c.label}  (${c.n})${tag}`;
    select.appendChild(opt);
  }
}

const FILTER_CLASSES = [
  "boundary-inbound",
  "boundary-outbound",
  "boundary-both",
  "halo-upstream",
  "halo-downstream",
  "halo-edge",
  "halo-compound",
  "compliance-pass",
  "compliance-fail",
].join(" ");

// The data-carrying resource types — the only ones that form the lineage backbone
// the boundary classification runs over. Mirrors `DATA_RESOURCE_TYPES` in
// `adaf.dbt.graph`: tests / semantic models / analyses are attachments ON or
// consumers OF data nodes, not lineage. Including them misclassifies — a childless
// `test` reads as an outbound leaf, and a model whose only child is a test reads as
// outbound — so they are excluded from BOTH the member set and the neighbour sets,
// exactly as the server-side `Graph` drops them from its node AND edge sets. Keeping
// this in sync with the Python set is what makes the filtered viewer agree with
// `sdag check`.
const DATA_RESOURCE_TYPES = new Set(["model", "source", "seed", "snapshot"]);
const isDataNode = (n) => DATA_RESOURCE_TYPES.has(n.data("resource_type"));

function restoreRehomed() {
  for (const { node, parent } of rehomedNodes) {
    if (node.inside()) node.move({ parent });
  }
  rehomedNodes = [];
}

// Layer compliance rings (T20) onto the filtered members from the selector's
// per-node annotations: a member with any failing obligation gets compliance-
// fail (red ring + glow), a boundary member with none gets compliance-pass.
function applyComplianceClasses() {
  const entry = complianceFor(currentFilter);
  if (!entry) return;
  const ann = entry.annotations || {};
  for (const [uid, a] of Object.entries(ann)) {
    const node = cy.getElementById(uid);
    if (node.empty()) continue;
    if (failingRuleIds(a).length) node.addClass("compliance-fail");
    else node.addClass("compliance-pass");
  }
}

function applyFilter() {
  if (!cy) return;
  cy.elements().removeClass(FILTER_CLASSES);
  restoreRehomed();

  if (currentView !== "full" || currentFilter === "__all__") {
    cy.elements().style({ display: "element" });
    return;
  }
  const targetCompoundId = `sel::${currentFilter}`;
  const compound = cy.getElementById(targetCompoundId);

  const members = cy.nodes(".entity").filter(
    (n) => (n.data("selectors") || []).includes(currentFilter),
  );
  if (members.length === 0) {
    cy.elements().style({ display: "none" });
    document.getElementById("status").textContent =
      `filter "${currentFilter}": no nodes on this branch`;
    return;
  }

  if (compound.nonempty()) {
    members.forEach((n) => {
      const cur = n.parent();
      const curId = cur.nonempty() ? cur.id() : null;
      if (curId !== targetCompoundId) {
        rehomedNodes.push({ node: n, parent: curId });
        n.move({ parent: targetCompoundId });
      }
    });
  }

  const memberIds = new Set(members.map((n) => n.id()));
  const isMember = (n) => memberIds.has(n.id());
  const hasExt = (n) => !isMember(n);

  // Classify over the data-node backbone only (see DATA_RESOURCE_TYPES): tests and
  // other attachments are dropped as members AND as neighbours, mirroring the
  // server-side Graph — so a childless test never reads as an outbound leaf, and a
  // model whose only child is a test is not pushed outbound by that test edge.
  const dataMembers = members.filter(isDataNode);

  const inboundBoundary = dataMembers.filter((m) => {
    const parents = m.incomers("node").filter(isDataNode);
    const internal = parents.filter(isMember);
    const external = parents.filter(hasExt);
    return external.length > 0 || internal.length === 0;
  });
  const outboundBoundary = dataMembers.filter((m) => {
    const children = m.outgoers("node").filter(isDataNode);
    const internal = children.filter(isMember);
    const external = children.filter(hasExt);
    return external.length > 0 || internal.length === 0;
  });
  const bothBoundary = inboundBoundary.intersection(outboundBoundary);
  const pureInbound = inboundBoundary.difference(bothBoundary);
  const pureOutbound = outboundBoundary.difference(bothBoundary);

  const upstreamExt = inboundBoundary.incomers("node").filter(isDataNode).filter(hasExt);
  const downstreamExt = outboundBoundary.outgoers("node").filter(isDataNode).filter(hasExt);

  const haloCompounds = upstreamExt.parents().union(downstreamExt.parents())
    .filter((n) => n.id() !== targetCompoundId);

  const internalEdges = cy.edges().filter((e) =>
    isMember(e.source()) && isMember(e.target())
  );
  const upstreamIds = new Set(upstreamExt.map((n) => n.id()));
  const downstreamIds = new Set(downstreamExt.map((n) => n.id()));
  const upstreamEdges = cy.edges().filter((e) =>
    upstreamIds.has(e.source().id()) && isMember(e.target())
  );
  const downstreamEdges = cy.edges().filter((e) =>
    isMember(e.source()) && downstreamIds.has(e.target().id())
  );

  const visible = compound
    .union(members)
    .union(internalEdges)
    .union(upstreamExt)
    .union(downstreamExt)
    .union(haloCompounds)
    .union(upstreamEdges)
    .union(downstreamEdges);

  cy.elements().style({ display: "none" });
  visible.style({ display: "element" });

  pureInbound.addClass("boundary-inbound");
  pureOutbound.addClass("boundary-outbound");
  bothBoundary.addClass("boundary-both");
  upstreamExt.addClass("halo-upstream");
  downstreamExt.addClass("halo-downstream");
  upstreamEdges.union(downstreamEdges).addClass("halo-edge");
  haloCompounds.addClass("halo-compound");

  // Compliance rings layer on top of the boundary colours.
  applyComplianceClasses();
}

function rerunWithFilter() {
  applyFilter();
  if (cy) runLayout(currentView, document.getElementById("status"), { elements: cy.elements(":visible") });
  renderCompliance(currentView === "full" ? currentFilter : "__all__");
}

// Layout fall-back plumbing (dagre 0.8.5 can throw on large compound graphs).
let _layoutFallback = null;
window.addEventListener("unhandledrejection", (e) => {
  if (_layoutFallback) {
    const fn = _layoutFallback; _layoutFallback = null;
    e.preventDefault();
    console.warn("dagre layout rejected — falling back to cose:", e.reason);
    fn();
  }
});

function runLayout(name, status, _data) {
  const visible = cy.elements(":visible");
  const count = visible.length;
  const label = currentFilter !== "__all__" && currentView === "full"
    ? `${name} graph · filter=${currentFilter} · ${count} visible`
    : `${name} graph · ${count} elements`;

  _layoutFallback = () => {
    const layout = visible.layout(FALLBACK_LAYOUT);
    layout.one("layoutstop", () => fitVisible(visible));
    layout.run();
    status.textContent = `${label} · layout: cose (dagre fallback)`;
  };
  try {
    const layout = visible.layout(LAYOUTS[name]);
    layout.one("layoutstop", () => fitVisible(visible));
    layout.run();
    setTimeout(() => { _layoutFallback = null; }, 1000);
    status.textContent = `${label} · layout: dagre`;
  } catch (err) {
    console.warn(`dagre layout threw sync for "${name}":`, err);
    if (_layoutFallback) { const fn = _layoutFallback; _layoutFallback = null; fn(); }
  }
}

// Fit-to-view on the FIRST load. The (synchronous, animate:false) layout fits before the canvas has
// its real pixel size at boot — the flex container is still resolving, the side panels that shrink #cy
// render right after, and web fonts that size node labels haven't loaded — so the super graph boots
// un-fitted. A ResizeObserver reacts to the container ACTUALLY getting/changing its size (the real
// cause, whenever it lands) and refits; web-font readiness covers label-metric shifts that don't
// resize the container; a double-rAF belt covers the case where nothing else fires. All idempotent
// (cy.fit is cheap). The observer self-disconnects after a short window so it never fights a user pan.
function fitOnFirstLoad() {
  // TRUE fit (like the "Fit to viewport" button) — NOT fitVisible: a wide super graph fits below the
  // MIN_VIEW_ZOOM legibility floor, and fitVisible would clamp the zoom UP to that floor, overflowing
  // the viewport. On first load we want the whole graph visible even if labels go small; the user can
  // zoom in after. (The floor still governs re-layout / resize, keeping labels legible there.)
  const refit = () => { if (cy) { cy.resize(); cy.fit(cy.elements(":visible"), 30); } };
  const el = document.getElementById("cy");
  if (el && typeof ResizeObserver !== "undefined") {
    let live = true;
    const ro = new ResizeObserver(() => { if (live) refit(); });
    ro.observe(el);  // fires immediately with the current size, then on every settle
    setTimeout(() => { live = false; ro.disconnect(); }, 1200);
  }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(refit).catch(() => {});
  requestAnimationFrame(() => requestAnimationFrame(refit));
}

function fitVisible(eles) {
  cy.fit(eles, 30);
  if (cy.zoom() < MIN_VIEW_ZOOM) {
    cy.zoom(MIN_VIEW_ZOOM);
    const bb = eles.boundingBox();
    const cx = cy.width() / 2;
    const cy_ = cy.height() / 2;
    cy.pan({
      x: cx - ((bb.x1 + bb.x2) / 2) * MIN_VIEW_ZOOM,
      y: cy_ - ((bb.y1 + bb.y2) / 2) * MIN_VIEW_ZOOM,
    });
  }
}

function renderMetadata(meta, view) {
  const lines = [`view: ${view}`];
  for (const [k, v] of Object.entries(meta || {})) {
    if (k === "compliance") continue;  // rendered in its own panel, not the raw stats dump
    const val = (typeof v === "object") ? JSON.stringify(v) : v;
    lines.push(`${k.padEnd(28)} ${val}`);
  }
  document.getElementById("metadata-body").textContent = lines.join("\n");
}

function renderBuildBanner() {
  const el = document.getElementById("build-banner");
  el.textContent = `build ${BUILD_ID}\nsrc   ${SOURCE}`;
}

// ── Boundary role (T38) ────────────────────────────────────────────────────
// A node's obligations and governance expectations MUST match its boundary role
// within the active selector. The per-selector annotations already carry the
// authoritative role + the ONLY applicable obligation rules per role
// (annotations.py drives this off the same lint registry), so the viewer reads
// the role straight from there rather than re-deriving it:
//   inbound  → freshness (TM-AU-01, sources) + volume-anomaly (MD-07).
//   outbound → contract (MD-02) + exposure (MD-11) + semantic model (MD-12).
//   both     → union of the above.
//   inner / no active filter → no boundary obligations at all.
// The semantic-model expectation is an OUTBOUND/BOTH obligation, so it is shown
// only for those roles — an inbound node is never marked as "missing a semantic
// model".
function boundaryAnnotationFor(uid) {
  const entry = complianceFor(currentFilter);
  if (!entry) return null;
  return (entry.annotations || {})[uid] || null;
}

function boundaryRoleOf(uid) {
  const a = boundaryAnnotationFor(uid);
  return a ? a.boundary : null;
}

// True when a semantic model is actually expected of this role (outbound/both).
function expectsSemanticModel(role) {
  return role === "outbound" || role === "both";
}

// ── Governance (T21) ──────────────────────────────────────────────────────
// Doc coverage, test count/types and semantic backing — sourced from the
// manifest data viewer.py stamps onto every entity node.
function governanceFacts(d) {
  const docs = d.has_description ? "documented" : "no description";
  const tcount = d.test_count || 0;
  const types = (d.test_types || []);
  const tests = tcount
    ? `${tcount} test${tcount === 1 ? "" : "s"}${types.length ? ` (${types.join(", ")})` : ""}`
    : "no tests";
  const semantic = d.semantic_backed ? "backs a semantic model" : "no semantic model";
  return { docs, tests, semantic };
}

// One-character status mark for an obligation rule (pass/fail/suppressed).
function ruleMark(status) {
  return status === "pass" ? "✓" : (status === "fail" ? "✗" : "•");
}

function governanceTooltipText(d) {
  const g = governanceFacts(d);
  const ann = boundaryAnnotationFor(d.id);
  const role = ann ? ann.boundary : null;
  const lines = [
    `${d.label || d.id}`,
    `${d.resource_type || "?"}${role ? `  ·  ${role} boundary` : ""}`,
    "",
    `docs:     ${d.has_description ? "✓ " : "✗ "}${g.docs}`,
    `tests:    ${g.tests}`,
  ];
  // Semantic backing is only an expectation for outbound/both — never surface a
  // "no semantic model" cross on an inbound (or unfiltered) node.
  if (expectsSemanticModel(role)) {
    lines.push(`semantic: ${d.semantic_backed ? "✓ " : "✗ "}${g.semantic}`);
  }
  // Role-tailored obligations (inbound → freshness/volume; outbound → contract/
  // exposure/semantic). Comes straight from the annotation's applicable rules.
  const rules = (ann && ann.rules) || [];
  if (rules.length) {
    lines.push("");
    lines.push(`obligations (${role}):`);
    for (const r of rules) {
      lines.push(`  ${ruleMark(r.status)} ${r.rule_id}  ${r.status}`);
    }
  }
  return lines.join("\n");
}

function governanceHtml(d) {
  const g = governanceFacts(d);
  const role = boundaryRoleOf(d.id);
  const yes = (b) => b
    ? `<span class="badge badge-pass">✓</span>`
    : `<span class="badge badge-warn">✗</span>`;
  const testBadge = (d.test_count || 0) > 0
    ? `<span class="badge badge-pass">${d.test_count}</span>`
    : `<span class="badge badge-warn">0</span>`;
  const rows = [
    `<div class="text-label uppercase tracking-wider text-[10px] mb-1">Governance</div>`,
    `<div class="gov-row">${yes(d.has_description)}<span class="text-body text-[11px]">${escapeHtml(g.docs)}</span></div>`,
    `<div class="gov-row">${testBadge}<span class="text-body text-[11px]">${escapeHtml(g.tests)}</span></div>`,
  ];
  // Only outbound/both nodes owe a semantic model, so only they show the row.
  if (expectsSemanticModel(role)) {
    rows.push(`<div class="gov-row">${yes(d.semantic_backed)}<span class="text-body text-[11px]">${escapeHtml(g.semantic)}</span></div>`);
  }
  return rows.join("");
}

// Per-node compliance detail for the active filter (rule-by-rule).
function complianceDetailHtml(uid) {
  const entry = complianceFor(currentFilter);
  if (!entry) return "";
  const a = (entry.annotations || {})[uid];
  if (!a) return "";
  const rows = (a.rules || []).map((r) => {
    const cls = r.status === "fail" ? "badge-fail" : (r.status === "pass" ? "badge-pass" : "badge-warn");
    return `<div class="gov-row py-0.5">` +
      `<span class="badge ${cls}">${escapeHtml(r.rule_id)}</span>` +
      `<span class="text-body text-[11px]">${escapeHtml(r.description)}</span></div>`;
  }).join("");
  return [
    `<div class="divider mt-2 pt-2">`,
    `<div class="text-label uppercase tracking-wider text-[10px] mb-1">Boundary obligations · ${escapeHtml(a.boundary)}</div>`,
    rows,
    `</div>`,
  ].join("");
}

function renderDetail(data) {
  const body = document.getElementById("detail-body");
  // Edges (and any non-entity) fall back to the compact JSON dump.
  if (!data || data.kind !== "entity") {
    const drop = new Set(["id", "colour", "parent"]);
    const out = {};
    for (const [k, v] of Object.entries(data || {})) {
      if (drop.has(k)) continue;
      if (v == null || (Array.isArray(v) && v.length === 0)) continue;
      out[k] = v;
    }
    body.classList.add("mono", "whitespace-pre");
    body.textContent = JSON.stringify(out, null, 2);
    return;
  }
  body.classList.remove("mono", "whitespace-pre");
  const head =
    `<div class="text-body text-[12px] mono break-all mb-1">${escapeHtml(data.label || data.id)}</div>` +
    `<div class="text-sub text-[10px] mb-2">${escapeHtml(data.resource_type || "")}` +
      `${data.schema ? " · " + escapeHtml(data.schema) : ""}` +
      `${data.materialized ? " · " + escapeHtml(data.materialized) : ""}</div>`;
  body.innerHTML = head + governanceHtml(data) + complianceDetailHtml(data.id);
}

// ── Hover tooltip plumbing ────────────────────────────────────────────────
let _tooltip = null;
function ensureTooltip() {
  if (_tooltip) return _tooltip;
  _tooltip = document.createElement("div");
  _tooltip.className = "cy-tooltip";
  _tooltip.style.position = "fixed";
  _tooltip.style.display = "none";
  document.body.appendChild(_tooltip);
  return _tooltip;
}
function showTooltip(evt) {
  const tip = ensureTooltip();
  tip.textContent = governanceTooltipText(evt.target.data());
  tip.style.display = "block";
  moveTooltip(evt);
}

// ── Super-node hover tooltip (T40) ─────────────────────────────────────────
// Collapsed super nodes (one per data product) get a tooltip mirroring the
// per-node detail: product name + compliance %/fails + the governance roll-up,
// reusing the same T33 summary helpers the detail card and node label use.
function superTooltipText(superName) {
  const comp = superComplianceSummary(superName);
  const gov = governanceRollup(superName);
  const lines = [superName];
  if (comp) {
    lines.push(`${comp.pct}% compliant · ${comp.failed}/${comp.total} obligations failed`);
  } else {
    lines.push("ungraded · no compliance data");
  }
  if (gov.total) {
    lines.push("");
    lines.push(`docs:     ${gov.documented}/${gov.total}`);
    lines.push(`tests:    ${gov.tested}/${gov.total}`);
    lines.push(`semantic: ${gov.semantic}/${gov.total}`);
  }
  // The selector's resolution rule (YAML) so the hover explains WHY nodes are in this product.
  const def = (cy.getElementById(superName).data() || {}).definition;
  const defStr = typeof def === "string" ? def : (def ? JSON.stringify(def, null, 2) : "");
  if (defStr) {
    lines.push("");
    if (defStr.includes("\n")) {
      lines.push("definition:");
      for (const l of defStr.split("\n")) lines.push(`  ${l}`);
    } else {
      lines.push(`definition: ${defStr}`);
    }
  }
  return lines.join("\n");
}
function showSuperTooltip(evt) {
  const tip = ensureTooltip();
  tip.textContent = superTooltipText(evt.target.data().id);
  tip.style.display = "block";
  moveTooltip(evt);
}
function moveTooltip(evt) {
  if (!_tooltip || _tooltip.style.display === "none") return;
  const oe = evt.originalEvent;
  if (!oe) return;
  const pad = 14;
  let x = oe.clientX + pad;
  let y = oe.clientY + pad;
  const w = _tooltip.offsetWidth || 200;
  const h = _tooltip.offsetHeight || 80;
  if (x + w > window.innerWidth) x = oe.clientX - w - pad;
  if (y + h > window.innerHeight) y = oe.clientY - h - pad;
  _tooltip.style.left = `${Math.max(4, x)}px`;
  _tooltip.style.top = `${Math.max(4, y)}px`;
}
function hideTooltip() {
  if (_tooltip) _tooltip.style.display = "none";
}

// ─────────────────────────────────────────────────────────────────────────
// Super-node boundary report
// ─────────────────────────────────────────────────────────────────────────
function buildBoundaryReport(superName) {
  const fullData = cache.full;
  if (!fullData) return null;

  const members = new Set();
  for (const e of fullData.elements) {
    if (e.data.kind === "entity" && (e.data.selectors || []).includes(superName)) {
      members.add(e.data.id);
    }
  }
  if (members.size === 0) return { superName, members: 0, ancestors: [], descendants: [] };

  const parentsOf = new Map();
  const childrenOf = new Map();
  for (const e of fullData.elements) {
    if (e.data.kind !== "lineage") continue;
    const { source, target } = e.data;
    (parentsOf.get(target) || parentsOf.set(target, []).get(target)).push(source);
    (childrenOf.get(source) || childrenOf.set(source, []).get(source)).push(target);
  }

  const labelMap = new Map();
  for (const e of fullData.elements) {
    if (e.data.kind === "entity") labelMap.set(e.data.id, e.data.label || e.data.id);
  }

  const ancestors = [];
  const descendants = [];
  for (const uid of members) {
    const parents = parentsOf.get(uid) || [];
    const children = childrenOf.get(uid) || [];
    const internalParents  = parents.filter((p) => members.has(p));
    const internalChildren = children.filter((c) => members.has(c));
    const externalParents  = parents.filter((p) => !members.has(p));
    const externalChildren = children.filter((c) => !members.has(c));

    if (externalParents.length > 0 || internalParents.length === 0) {
      ancestors.push({
        label: labelMap.get(uid) || uid,
        uid,
        inbound_external: externalParents.map((p) => labelMap.get(p) || p).sort(),
      });
    }
    if (externalChildren.length > 0 || internalChildren.length === 0) {
      descendants.push({
        label: labelMap.get(uid) || uid,
        uid,
        outbound_external: externalChildren.map((c) => labelMap.get(c) || c).sort(),
      });
    }
  }
  ancestors.sort((a, b) => a.label.localeCompare(b.label));
  descendants.sort((a, b) => a.label.localeCompare(b.label));
  return { superName, members: members.size, ancestors, descendants };
}

function renderBoundaryReport(report) {
  const body = document.getElementById("detail-body");
  if (!report) {
    body.classList.add("mono", "whitespace-pre");
    body.textContent = "click a node…";
    return;
  }
  // Lead with the SUMMARISED product health card (HTML badges — the same
  // visuals praised on the per-node detail), then the boundary tree as <pre>.
  body.classList.remove("mono", "whitespace-pre");
  const out = [`super-node: ${report.superName}`, `members:    ${report.members}`, ""];

  out.push(`▼ ANCESTORS  (sub-graph roots; ${report.ancestors.length})`);
  if (report.ancestors.length === 0) out.push("  (none)");
  for (const a of report.ancestors) {
    out.push(`  • ${a.label}`);
    if (a.inbound_external.length === 0) {
      out.push("      ← no external inbound models");
    } else {
      out.push(`      ← inbound (${a.inbound_external.length}):`);
      for (const p of a.inbound_external) out.push(`          · ${p}`);
    }
  }
  out.push("");
  out.push(`▲ DESCENDANTS  (sub-graph leaves; ${report.descendants.length})`);
  if (report.descendants.length === 0) out.push("  (none)");
  for (const d of report.descendants) {
    out.push(`  • ${d.label}`);
    if (d.outbound_external.length === 0) {
      out.push("      → no external outbound models");
    } else {
      out.push(`      → outbound (${d.outbound_external.length}):`);
      for (const c of d.outbound_external) out.push(`          · ${c}`);
    }
  }
  // The selector's resolution rule (YAML, embedded on the super-node by the builder) — shown in a
  // code block so the sidebar explains WHY nodes are in this product.
  const def = (cy.getElementById(report.superName).data() || {}).definition;
  const defStr = typeof def === "string" ? def : (def ? JSON.stringify(def, null, 2) : "");
  const defHtml = defStr
    ? `<div class="text-label uppercase tracking-wider text-[10px] mb-1">selector definition</div>` +
      `<pre class="mono whitespace-pre text-[11px] mb-2" style="background:var(--canvas);` +
      `border:1px solid var(--border);border-radius:6px;padding:6px 8px;margin:0 0 8px 0;overflow-x:auto">` +
      `${escapeHtml(defStr)}</pre>`
    : "";
  const head =
    `<div class="text-body text-[12px] mono break-all mb-1">${escapeHtml(report.superName)} ` +
    `<span class="text-sub">· ${report.members} members</span></div>` +
    defHtml;
  const tree = `<pre class="mono whitespace-pre text-[11px]" style="margin:0">${escapeHtml(out.join("\n"))}</pre>`;
  body.innerHTML = head + superSummaryHtml(report.superName) + tree;
}

function clearDetail() {
  const body = document.getElementById("detail-body");
  body.classList.add("mono");
  body.classList.remove("whitespace-pre");
  body.innerHTML = "";
  body.textContent = "click a node…";
}

function buildLegend() {
  const wrap = document.getElementById("legend");
  for (const [kind, colour] of Object.entries(RESOURCE_COLOURS)) {
    const row = document.createElement("div");
    row.className = "flex items-center gap-2";
    row.innerHTML = `
      <span style="background:${colour}" class="inline-block w-3 h-3 rounded-sm"></span>
      <span class="text-body">${kind}</span>`;
    wrap.appendChild(row);
  }
  // Super-graph product-health ring legend (T33).
  const superLegend = document.createElement("div");
  superLegend.className = "mt-2 pt-2 divider space-y-1";
  superLegend.innerHTML = `
    <div class="text-label uppercase tracking-wider text-[10px]">super-node health</div>
    <div class="flex items-center gap-2">
      <span class="inline-block w-3 h-3 rounded-sm" style="border:3px solid var(--ok-text)"></span>
      <span class="text-body">compliant (≥80%)</span>
    </div>
    <div class="flex items-center gap-2">
      <span class="inline-block w-3 h-3 rounded-sm" style="border:3px solid var(--warn-text)"></span>
      <span class="text-body">at risk (50–79%)</span>
    </div>
    <div class="flex items-center gap-2">
      <span class="inline-block w-3 h-3 rounded-sm" style="border:3px solid var(--fail-text)"></span>
      <span class="text-body">failing (&lt;50%)</span>
    </div>
    <div class="flex items-center gap-2">
      <span class="inline-block w-3 h-3 rounded-sm" style="border:2px dashed var(--text-muted)"></span>
      <span class="text-body">ungraded (no data)</span>
    </div>`;
  wrap.appendChild(superLegend);

  const filterLegend = document.createElement("div");
  filterLegend.id = "filter-legend";
  filterLegend.className = "mt-2 pt-2 divider space-y-1 hidden";
  filterLegend.innerHTML = `
    <div class="text-label uppercase tracking-wider text-[10px]">when filtered</div>
    <div class="flex items-center gap-2">
      <span style="background:#10b981" class="inline-block w-3 h-3 rounded-sm"></span>
      <span class="text-body">inbound boundary</span>
    </div>
    <div class="flex items-center gap-2">
      <span style="background:#f59e0b" class="inline-block w-3 h-3 rounded-sm"></span>
      <span class="text-body">outbound boundary</span>
    </div>
    <div class="flex items-center gap-2">
      <span style="background:#f43f5e" class="inline-block w-3 h-3 rounded-sm"></span>
      <span class="text-body">both (in &amp; out)</span>
    </div>
    <div class="flex items-center gap-2">
      <span class="inline-block w-3 h-3 rounded-full" style="border:3px solid var(--fail-text)"></span>
      <span class="text-body">failing obligation</span>
    </div>
    <div class="flex items-center gap-2">
      <span class="inline-block w-3 h-3 rounded-full" style="border:3px solid var(--ok-text)"></span>
      <span class="text-body">compliant boundary</span>
    </div>
    <div class="flex items-center gap-2">
      <span style="background:#334155" class="inline-block w-3 h-3 rounded-sm"></span>
      <span class="text-body">halo upstream</span>
    </div>
    <div class="flex items-center gap-2">
      <span style="background:#3b3651" class="inline-block w-3 h-3 rounded-sm"></span>
      <span class="text-body">halo downstream</span>
    </div>`;
  wrap.appendChild(filterLegend);
}

function setFilterLegendVisible(visible) {
  const el = document.getElementById("filter-legend");
  if (el) el.classList.toggle("hidden", !visible);
}

// ─────────────────────────────────────────────────────────────────────────
// Collapsible sidebar (T39) — toggles .sidebar-collapsed on #app-root so the
// canvas reclaims the sidebar's width, persists the choice in localStorage, and
// resizes+refits cytoscape so the graph reflows into (or out of) the new space.
// ─────────────────────────────────────────────────────────────────────────
const SIDEBAR_KEY = "sdag-sidebar-collapsed";

function applySidebarState(collapsed, { persist = true, refit = true } = {}) {
  const root = document.getElementById("app-root");
  if (!root) return;
  root.classList.toggle("sidebar-collapsed", collapsed);
  const btn = document.getElementById("btn-sidebar-toggle");
  if (btn) {
    btn.textContent = collapsed ? "⟩" : "⟨";
    btn.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
  }
  if (persist) {
    try { localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0"); } catch (e) { /* private mode */ }
  }
  // The canvas width only changes after the class flip lands; resize+fit on the
  // next frame so cytoscape measures the final container size.
  if (refit && cy) {
    requestAnimationFrame(() => { cy.resize(); cy.fit(undefined, 30); });
  }
}

function sidebarCollapsedSaved() {
  try { return localStorage.getItem(SIDEBAR_KEY) === "1"; } catch (e) { return false; }
}

function toggleSidebar() {
  const root = document.getElementById("app-root");
  applySidebarState(!(root && root.classList.contains("sidebar-collapsed")));
}

// ─────────────────────────────────────────────────────────────────────────
// Wire up
// ─────────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await loadTokens();  // T35: pull the externalised design tokens BEFORE first paint
  applyTheme(currentTheme, { persist: false });  // sync the toggle label to the booted theme
  renderBuildBanner();
  buildLegend();
  // Restore the sidebar collapsed/expanded choice BEFORE the first render so
  // the initial cy.fit() already accounts for the canvas's real width.
  applySidebarState(sidebarCollapsedSaved(), { persist: false, refit: false });
  document.getElementById("btn-sidebar-toggle").addEventListener("click", toggleSidebar);
  document.getElementById("btn-theme").addEventListener("click", toggleTheme);
  document.getElementById("btn-full" ).addEventListener("click", () => showView("full"));
  document.getElementById("btn-super").addEventListener("click", () => showView("super"));
  document.getElementById("btn-fit"   ).addEventListener("click", () => cy && cy.fit());
  document.getElementById("btn-relayout").addEventListener("click", () => {
    if (cy) runLayout(currentView, document.getElementById("status"));
  });
  document.getElementById("filter-selector").addEventListener("change", (e) => {
    currentFilter = e.target.value;
    setFilterLegendVisible(currentFilter !== "__all__");
    if (currentFilter !== "__all__" && currentView !== "full") {
      showView("full");  // showView calls applyFilter() + renderCompliance() + syncUrl()
      return;
    }
    rerunWithFilter();
    syncUrl();
  });

  window.addEventListener("popstate", async () => {
    suppressUrlSync = true;
    try {
      const view = applyStateFromUrl();
      await showView(view);
    } finally {
      suppressUrlSync = false;
    }
  });

  try {
    await fetchView("full");
    populateFilterDropdown(cache.full);

    const initialView = applyStateFromUrl();
    currentView = initialView;
    const normalised = canonicalUrl();
    if (normalised !== currentUrl()) {
      window.history.replaceState(null, "", normalised);
    }
    await showView(initialView);
    fitOnFirstLoad();
  } catch (e) {
    document.getElementById("status").textContent = `error: ${e.message}`;
    console.error(e);
  }
});
