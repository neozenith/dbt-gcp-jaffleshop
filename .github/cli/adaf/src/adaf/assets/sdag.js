// sdag.js — viewer logic for the super-DAG.
//
// Templated by `sdag.py write_outputs()` at build time:
//   {{BUILD_ID}}  → timestamp of the generate run (cache-bust + banner)
//   {{SOURCE}}    → dbt target/ path the manifest was read from
// If you ever load this file directly without templating, both will appear
// literally as `{{...}}` — that's the signal that the build step was skipped.

// ─────────────────────────────────────────────────────────────────────────
// Palette — mirrors NODE_COLOURS in sdag.py so the JSON `colour` hint and
// CSS selectors agree.
// ─────────────────────────────────────────────────────────────────────────
const RESOURCE_COLOURS = {
  model:    "#3b82f6",
  test:     "#a855f7",
  seed:     "#10b981",
  snapshot: "#f59e0b",
  source:   "#6b7280",
  analysis: "#ec4899",
  exposure: "#ef4444",
  metric:   "#14b8a6",
};

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

// ─────────────────────────────────────────────────────────────────────────
// URL state sync — deep-linkable view + filter with Back/Forward support.
//
// The viewer's two pieces of user-facing state (which view is active, and
// which selector is filtered to) are mirrored into the query string so a URL
// can be copied/shared to land someone on the exact same view, AND so the
// browser Back/Forward buttons walk through prior view+filter combinations.
//
//   ?view=full|super     which view is showing
//   ?selector=<name>     active full-graph filter (omitted when "(show all)")
//
// History semantics:
//   • User-driven changes use pushState — each toggle is its own Back step.
//   • The initial landing URL is normalised with replaceState (boot), so it
//     doesn't leave a duplicate first entry to click Back through.
//   • A no-op guard skips writes when the canonical URL already matches (e.g.
//     clicking the already-active view), so history never fills with dupes.
//   • Applying state in response to a popstate event sets `suppressUrlSync`
//     so re-rendering the restored state can't push a fresh entry (which would
//     fight the Back button it's reacting to).
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
    // Validate `view` here so a junk value in a shared link can't put the
    // viewer in an undefined state — callers fall back to their default.
    view: view === "full" || view === "super" ? view : null,
    selector: selector || null,  // validated against the dropdown before use
  };
}

// Build the query string that REPRESENTS the current in-memory state. Keeping
// this separate from the write lets both the no-op guard and the boot
// normalisation compare against it without duplicating the param logic.
function canonicalUrl() {
  const params = new URLSearchParams(window.location.search);
  params.set(URL_PARAM_VIEW, currentView);
  if (currentFilter && currentFilter !== "__all__") {
    params.set(URL_PARAM_SELECTOR, currentFilter);
  } else {
    // Keep the URL clean: "(show all)" is the absence of a filter, so drop
    // the param entirely rather than encoding the sentinel "__all__".
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

// Resolve the URL's view+filter into live state: validate the selector against
// the populated dropdown (a stale/unknown selector in a shared link degrades
// to "(show all)"), sync the dropdown + legend, and return the view to show.
// Shared by boot and the popstate handler so both restore state identically.
function applyStateFromUrl() {
  const urlState = readUrlState();
  const select = document.getElementById("filter-selector");
  const valid =
    urlState.selector &&
    Array.from(select.options).some((o) => o.value === urlState.selector);
  currentFilter = valid ? urlState.selector : "__all__";
  select.value = currentFilter;
  setFilterLegendVisible(currentFilter !== "__all__");
  // Explicit ?view wins. With no ?view, default to the full graph when a
  // filter is active (so the filter is visible) — otherwise the super summary.
  return urlState.view || (currentFilter !== "__all__" ? "full" : "super");
}

// ─────────────────────────────────────────────────────────────────────────
// Cytoscape stylesheet (shared across both views; class-driven)
// ─────────────────────────────────────────────────────────────────────────
const STYLE = [
  // Default leaf entity node. Labels are pure white with a dark outline so
  // they stay legible across every resource_type colour (most entity colours
  // are mid-to-dark blues / purples / grays). `min-zoomed-font-size` keeps
  // labels from disappearing when the canvas is zoomed out to fit thousands
  // of nodes in the full-graph view.
  {
    selector: "node",
    style: {
      "background-color": "data(colour)",
      "border-width": 1,
      "border-color": "#0f172a",
      "label": "data(label)",
      "color": "#ffffff",
      "font-size": 9,
      "font-weight": 600,
      "font-family": "ui-monospace, monospace",
      "text-valign": "center",
      "text-halign": "center",
      "text-outline-color": "#0f172a",
      "text-outline-width": 1.5,
      "text-max-width": 80,
      "text-wrap": "ellipsis",
      "width": 18,
      "height": 18,
    },
  },

  // Per-resource_type sizing tweaks
  { selector: "node.entity-model",    style: { width: 22, height: 22 } },
  { selector: "node.entity-test",     style: { width: 12, height: 12, "font-size": 7 } },
  { selector: "node.entity-source",   style: { shape: "round-rectangle", width: 26, height: 16 } },
  { selector: "node.entity-snapshot", style: { shape: "diamond", width: 20, height: 20 } },
  { selector: "node.entity-seed",     style: { shape: "round-pentagon", width: 18, height: 18 } },

  // Compound (selector) parent nodes
  {
    selector: "node.selector-compound",
    style: {
      "background-color": "#1e293b",
      "background-opacity": 0.35,
      "border-color": "#38bdf8",
      "border-width": 1,
      "label": "data(label)",
      "color": "#ffffff",
      "text-outline-color": "#0f172a",
      "text-outline-width": 1.5,
      "text-valign": "top",
      "text-halign": "left",
      "font-size": 11,
      "font-weight": 600,
      "padding": 16,
      "shape": "round-rectangle",
    },
  },
  {
    selector: "node.selector-compound.unmatched",
    style: { "border-color": "#475569", "color": "#64748b" },
  },

  // Super nodes (collapsed-selector view) — sized by member count. Text uses
  // the same white-on-dark-outline strategy as the entity nodes so labels
  // stay legible whether they sit inside the (light blue) box or spill onto
  // the (dark) canvas at low zoom. `min-zoomed-font-size` is the load-bearing
  // bit: dagre's auto-fit zooms out to ~0.07 on 60 super-nodes, and at that
  // scale a 13px font would render at 1px (sub-pixel — invisible). The
  // property tells cytoscape to NEVER scale this label below 12px regardless
  // of canvas zoom, so labels stay readable from any viewport.
  {
    selector: "node.super",
    style: {
      "background-color": "#0369a1",
      "background-opacity": 0.95,
      "border-color": "#7dd3fc",
      "border-width": 2,
      "shape": "round-rectangle",
      "label": "data(label)",
      "color": "#ffffff",
      "font-size": 22,
      "font-weight": 700,
      "font-family": "ui-monospace, monospace",
      "padding": 14,
      "text-valign": "center",
      "text-halign": "center",
      "text-wrap": "wrap",
      "text-max-width": 220,
      "text-outline-color": "#0f172a",
      "text-outline-width": 3,
      // Size scales with log1p(n_members) — see sdag.py for the rationale.
      // log_members domain is ~0 (=ln(1+1)≈0.7 — smallest selector) to ~7.8
      // (=ln(1+2400) for the catch-all), so the mapData range covers the
      // full visual budget. Use width and height proportionally so the
      // node aspect stays consistent.
      "width": "mapData(log_members, 0, 8, 110, 380)",
      "height": "mapData(log_members, 0, 8, 70, 240)",
    },
  },
  {
    selector: "node.super.unmatched",
    style: { "background-color": "#475569", "border-color": "#334155" },
  },

  // Lineage edges in the full view
  {
    selector: "edge.edge-lineage",
    style: {
      "width": 1,
      "line-color": "#475569",
      "curve-style": "bezier",
      "target-arrow-shape": "triangle",
      "target-arrow-color": "#475569",
      "arrow-scale": 0.6,
      "opacity": 0.6,
    },
  },

  // Aggregated edges in the super view — width scales with log1p(count),
  // same heavy-tail rationale as the super-node sizing. log_count spans
  // ~0 to ~6.2 (=ln(1+460)) so the mapData range covers the full budget.
  // Edge labels are also bumped so the count is readable at the zoom-floor.
  {
    selector: "edge[count]",
    style: {
      "width": "mapData(log_count, 0, 6.5, 1.5, 14)",
      "line-color": "#7dd3fc",
      "target-arrow-color": "#7dd3fc",
      "curve-style": "bezier",
      "target-arrow-shape": "triangle",
      "label": "data(count)",
      "color": "#bae6fd",
      "font-size": 16,
      "font-weight": 700,
      "text-background-color": "#0f172a",
      "text-background-opacity": 0.9,
      "text-background-padding": 3,
      "opacity": 0.85,
    },
  },

  // ── Filtered-view boundary annotations ───────────────────────────────
  // Only applied while a selector filter is active. The colours encode the
  // node's role in the sub-graph's lineage interface:
  //   inbound  (green)  — sub-graph root: nothing upstream of it is in the
  //                        same selector, so it's where external lineage
  //                        crosses INTO the sub-graph.
  //   outbound (amber)  — sub-graph leaf: nothing downstream of it is in the
  //                        same selector, so it's where lineage crosses OUT.
  //   isolated (rose)   — both inbound AND outbound (singleton member);
  //                        applied via class precedence (last rule wins).
  // Halo nodes are the 1-hop external neighbours of the boundary nodes —
  // they get muted slate colours and partial opacity so they read as
  // "context" rather than as part of the selected selector.
  { selector: "node.boundary-inbound", style: {
      "background-color": "#10b981",
      "border-color": "#6ee7b7",
      "border-width": 3,
    } },
  { selector: "node.boundary-outbound", style: {
      "background-color": "#f59e0b",
      "border-color": "#fcd34d",
      "border-width": 3,
    } },
  { selector: "node.boundary-both", style: {
      "background-color": "#f43f5e",
      "border-color": "#fb7185",
      "border-width": 3,
    } },
  { selector: "node.halo-upstream", style: {
      "background-color": "#334155",
      "border-color": "#64748b",
      "opacity": 0.75,
    } },
  { selector: "node.halo-downstream", style: {
      "background-color": "#3b3651",
      "border-color": "#6b5fa3",
      "opacity": 0.75,
    } },
  // Halo edges — connections crossing the sub-graph boundary. Made dashed
  // and dimmer than internal edges so the eye reads them as context.
  { selector: "edge.halo-edge", style: {
      "line-color": "#64748b",
      "target-arrow-color": "#64748b",
      "line-style": "dashed",
      "opacity": 0.6,
    } },
  // Halo compound (the parent selector compound that wraps an external
  // neighbour). Rendered as a thinner, more muted box than the focused
  // selector's compound so the focus reads clearly.
  { selector: "node.selector-compound.halo-compound", style: {
      "border-color": "#475569",
      "border-style": "dashed",
      "background-opacity": 0.15,
      "color": "#94a3b8",
    } },

  // Selection highlight (kept LAST so it overrides boundary borders when
  // the user has explicitly tapped a node).
  { selector: ":selected", style: { "border-color": "#fbbf24", "border-width": 4 } },
];

// ─────────────────────────────────────────────────────────────────────────
// Layout config — Dagre per requirements. `cytoscape-dagre` 2.5 / dagre 0.8.5
// can throw on very large compound graphs (`assignOrder` TypeError); the
// `fallback` is used by runLayout() to degrade to a force-directed pass when
// that happens, so the viewer never ends up with an empty canvas.
// ─────────────────────────────────────────────────────────────────────────
// `fit: false` — we run our own fit-with-floor in fitVisible() afterwards.
// Cytoscape's `cy.fit()` ignores minZoom and zooms out to 0.07 on 60+
// super-nodes, rendering all labels sub-pixel. The hard truth here: cytoscape
// does NOT scale text up at low zoom; `min-zoomed-font-size` is a HIDE
// threshold, not a render-floor. So the only way to keep labels legible
// is to refuse to zoom out below the level where the font is readable.
const LAYOUTS = {
  full: {
    name: "dagre",
    rankDir: "LR",
    nodeSep: 14,
    rankSep: 80,
    edgeSep: 4,
    ranker: "tight-tree",
    acyclicer: "greedy",
    animate: false,
    fit: false,
    padding: 30,
  },
  super: {
    name: "dagre",
    rankDir: "LR",
    // Tighter than the full graph: the super view only has ~60 nodes total,
    // and we want them compact enough that the auto-fit (or the floor-clamp)
    // shows most of them in-viewport without panning.
    nodeSep: 14,
    rankSep: 70,
    ranker: "tight-tree",
    acyclicer: "greedy",
    animate: false,
    fit: false,
    padding: 30,
  },
};
const FALLBACK_LAYOUT = {
  name: "cose",
  animate: false,
  fit: false,
  padding: 30,
  idealEdgeLength: 80,
  nodeRepulsion: 6000,
  gravity: 0.4,
};
const MIN_VIEW_ZOOM = 0.45;  // floor at which super-node labels stay legible

// ─────────────────────────────────────────────────────────────────────────
// Data loading
// ─────────────────────────────────────────────────────────────────────────
async function fetchView(name) {
  if (cache[name]) return cache[name];
  const file = name === "full" ? "full_graph.json" : "super_graph.json";
  const status = document.getElementById("status");
  status.textContent = `loading ${file}…`;
  // Three layers of cache-bust: build_id query-string, fetch cache: no-store,
  // and the server end_headers override that sends Cache-Control: no-store.
  // The query-string is the load-bearing one — even with disk caches and
  // proxies in the loop, a new build_id forces a fresh URL.
  const r = await fetch(`${file}?v=${encodeURIComponent(BUILD_ID)}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${file}: ${r.status} ${r.statusText}`);
  const data = await r.json();
  cache[name] = data;
  return data;
}

// ─────────────────────────────────────────────────────────────────────────
// Rendering
// ─────────────────────────────────────────────────────────────────────────
async function showView(name) {
  currentView = name;
  document.getElementById("btn-full" ).classList.toggle("bg-sky-600", name === "full");
  document.getElementById("btn-super").classList.toggle("bg-sky-600", name === "super");

  const data = await fetchView(name);
  // First time we see the full graph, populate the selector-filter dropdown
  // from its compound nodes. Super graph also has selectors-as-nodes but we
  // key the filter to the full graph's compound ids (`sel::<name>`).
  if (name === "full") populateFilterDropdown(data);

  const status = document.getElementById("status");
  status.textContent = `rendering ${data.elements.length} elements…`;

  if (cy) { cy.destroy(); cy = null; }
  cy = cytoscape({
    container: document.getElementById("cy"),
    elements: data.elements,
    style: STYLE,
    // Defer layout to runLayout() so we can try Dagre and fall back if it
    // throws (compound-graph edge case at scale).
    layout: { name: "preset" },
    wheelSensitivity: 0.2,
    minZoom: 0.05,
    maxZoom: 4,
  });

  // Apply the active filter before layout so dagre only sees the visible
  // sub-graph and packs it tightly. A no-op when currentFilter === "__all__"
  // or when we're in the super view.
  applyFilter();
  runLayout(name, status, data);

  // Super-node taps get the boundary report (ancestors + descendants of the
  // underlying sub-graph). Everything else gets the generic data dump.
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

  renderMetadata(data.metadata, name);
  // Single choke-point for view changes: every path that lands here (button
  // click, filter auto-switch, boot) keeps the URL in lock-step with state.
  syncUrl();
}

// ─────────────────────────────────────────────────────────────────────────
// Selector filter — populates the dropdown from the full-graph compounds
// (sorted alphabetically, with member counts), and applies the choice to
// the live cy instance by hiding everything outside the picked compound.
// ─────────────────────────────────────────────────────────────────────────
function populateFilterDropdown(fullGraphData) {
  const select = document.getElementById("filter-selector");
  // Skip if we've already populated — the dropdown options outlive view
  // switches; we don't want to clobber the user's choice on every render.
  if (select.options.length > 1) return;
  const compounds = fullGraphData.elements
    .filter((e) => e.data && e.data.kind === "selector_compound")
    .map((e) => ({ name: e.data.selector, label: e.data.label, n: e.data.n_members }))
    .sort((a, b) => a.label.localeCompare(b.label));
  for (const c of compounds) {
    const opt = document.createElement("option");
    opt.value = c.name;
    opt.textContent = `${c.label}  (${c.n})`;
    select.appendChild(opt);
  }
}

// Classes the filter applies / removes. Listed once so the
// applyFilter() teardown path can clear them all in a single call.
const FILTER_CLASSES = [
  "boundary-inbound",
  "boundary-outbound",
  "boundary-both",
  "halo-upstream",
  "halo-downstream",
  "halo-edge",
  "halo-compound",
].join(" ");

function applyFilter() {
  if (!cy) return;
  // Clear any previous filter classes — they're stateful, and a view switch
  // (or a filter change) should start from a clean slate.
  cy.elements().removeClass(FILTER_CLASSES);

  // Filter only makes sense for the full graph — the super graph already
  // has one node per selector, so filtering by selector would collapse it
  // to a single dot. Show everything when in super view.
  if (currentView !== "full" || currentFilter === "__all__") {
    cy.elements().style({ display: "element" });
    return;
  }
  const targetCompoundId = `sel::${currentFilter}`;
  const compound = cy.getElementById(targetCompoundId);
  if (compound.length === 0) {
    // Selector exists in the dropdown but has zero members on this branch —
    // hide everything and surface the empty state on the status bar.
    cy.elements().style({ display: "none" });
    document.getElementById("status").textContent =
      `filter "${currentFilter}": no nodes on this branch`;
    return;
  }

  // ── Sub-graph members + boundary classification ─────────────────────
  //
  // Refined semantics (see classify_boundary() in sdag.py for the spec
  // and test_sdag.py for the lock-in tests):
  //
  //   inbound  := has at least one external parent  OR  no internal parents
  //   outbound := has at least one external child   OR  no internal children
  //   both     := inbound ∩ outbound  (rendered rose so a single node
  //               doesn't get both green and amber styles fighting each
  //               other for precedence)
  //   interior := neither (only internal neighbours, both directions)
  //
  // The "OR no internal parents/children" arms preserve the legacy
  // topological root/leaf classification for sub-graphs whose roots or
  // leaves don't actually have external lineage (e.g. a seed at the top).
  // The "external parent/child" arms are the new check — they catch
  // members that look interior topologically but actually ref a model
  // outside the selector (the bluefield_bigw case).
  const members = compound.children();
  const memberIds = new Set(members.map((n) => n.id()));
  const isMember = (n) => memberIds.has(n.id());
  const hasExt = (n) => !isMember(n);

  const inboundBoundary = members.filter((m) => {
    const parents = m.incomers("node");
    const internal = parents.filter(isMember);
    const external = parents.filter(hasExt);
    return external.length > 0 || internal.length === 0;
  });
  const outboundBoundary = members.filter((m) => {
    const children = m.outgoers("node");
    const internal = children.filter(isMember);
    const external = children.filter(hasExt);
    return external.length > 0 || internal.length === 0;
  });
  const bothBoundary = inboundBoundary.intersection(outboundBoundary);
  const pureInbound = inboundBoundary.difference(bothBoundary);
  const pureOutbound = outboundBoundary.difference(bothBoundary);

  // ── 1-hop halo: external neighbours of the boundary members ─────────
  // Halo from EVERY inbound/outbound member (including "both"), not just
  // the topological roots/leaves — this is the part the old code missed
  // for interior members with external refs.
  const upstreamExt = inboundBoundary.incomers("node").filter(hasExt);
  const downstreamExt = outboundBoundary.outgoers("node").filter(hasExt);

  // Halo compounds: the parent selector-compound of each external halo
  // node. Showing these gives the user the "and their respective compound
  // nodes around them too" view — you can see which OTHER selectors the
  // current selector reaches into / is fed from.
  const haloCompounds = upstreamExt.parents().union(downstreamExt.parents())
    .filter((n) => n.id() !== targetCompoundId);

  // ── Visible edge set ────────────────────────────────────────────────
  // 1. Internal edges (both endpoints are members)
  // 2. Halo edges from upstream externals into ANY member (cytoscape's
  //    incomers/outgoers don't go across hidden elements, so we filter
  //    the full edge set directly)
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

  // ── Apply annotation classes ────────────────────────────────────────
  // "Both" gets the rose-coloured boundary-both class (formerly named
  // boundary-isolated; same colour, broader meaning under the new rules).
  pureInbound.addClass("boundary-inbound");
  pureOutbound.addClass("boundary-outbound");
  bothBoundary.addClass("boundary-both");
  upstreamExt.addClass("halo-upstream");
  downstreamExt.addClass("halo-downstream");
  upstreamEdges.union(downstreamEdges).addClass("halo-edge");
  haloCompounds.addClass("halo-compound");
}

function rerunWithFilter() {
  // Called when the filter dropdown changes. Re-layout so dagre packs the
  // visible subset cleanly rather than leaving a sparse canvas with the
  // selected sub-tree marooned in one corner.
  applyFilter();
  if (cy) runLayout(currentView, document.getElementById("status"), { elements: cy.elements(":visible") });
}

// Layout fall-back plumbing. Dagre 0.8.5 (the version cytoscape-dagre 2.5
// pins) throws a TypeError in `assignOrder` when laying out very large
// compound graphs with disconnected components. We install a one-shot
// rejection handler around the .run() call so we can degrade to `cose`
// without leaving the viewer with an empty canvas.
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
  // Always layout against the visible subset only. Without this, a filter
  // pick leaves dagre arranging hidden nodes too, and the visible cluster
  // ends up in one tight corner with the rest of the canvas blank.
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
    // If we got here without throwing, clear the fallback after a tick so
    // genuinely unrelated rejections still surface.
    setTimeout(() => { _layoutFallback = null; }, 1000);
    status.textContent = `${label} · layout: dagre`;
  } catch (err) {
    console.warn(`dagre layout threw sync for "${name}":`, err);
    if (_layoutFallback) { const fn = _layoutFallback; _layoutFallback = null; fn(); }
  }
}

function fitVisible(eles) {
  // Try the natural fit first. If the zoom result is below MIN_VIEW_ZOOM
  // (labels would render sub-pixel), clamp to the floor and center the
  // bbox on the viewport — partial graph is preferable to unreadable graph.
  cy.fit(eles, 30);
  if (cy.zoom() < MIN_VIEW_ZOOM) {
    cy.zoom(MIN_VIEW_ZOOM);
    const bb = eles.boundingBox();
    const cx = cy.width() / 2;
    const cy_ = cy.height() / 2;
    // pan(x,y) sets the offset between model (0,0) and viewport (0,0). To
    // put the bbox center at (cx, cy_), pan.x = cx - bbCx * zoom.
    cy.pan({
      x: cx - ((bb.x1 + bb.x2) / 2) * MIN_VIEW_ZOOM,
      y: cy_ - ((bb.y1 + bb.y2) / 2) * MIN_VIEW_ZOOM,
    });
  }
}

function renderMetadata(meta, view) {
  const lines = [`view: ${view}`];
  for (const [k, v] of Object.entries(meta || {})) {
    const val = (typeof v === "object") ? JSON.stringify(v) : v;
    lines.push(`${k.padEnd(28)} ${val}`);
  }
  document.getElementById("metadata-body").textContent = lines.join("\n");
}

function renderBuildBanner() {
  // Surface the build id + source path so a stale page is obvious: if the
  // banner doesn't match what `sdag.py generate` last printed, you're
  // looking at a cached HTML and need to hard-reload (Cmd+Shift+R).
  const el = document.getElementById("build-banner");
  el.textContent = `build ${BUILD_ID}\nsrc   ${SOURCE}`;
}

function renderDetail(data) {
  // Compact, JSON-ish dump. Drop noisy fields.
  const drop = new Set(["id", "colour", "parent"]);
  const out = {};
  for (const [k, v] of Object.entries(data)) {
    if (drop.has(k)) continue;
    if (v == null || (Array.isArray(v) && v.length === 0)) continue;
    out[k] = v;
  }
  document.getElementById("detail-body").textContent = JSON.stringify(out, null, 2);
}

// ─────────────────────────────────────────────────────────────────────────
// Super-node boundary report
//
// When the user clicks a super-node in the collapsed view we want to surface
// the *interface* of its underlying sub-graph — which members are the
// roots/leaves of the local lineage, and what the sub-graph reaches into /
// is fed from on the outside.
//
//   ancestors  = members with NO incoming edges from other members of the
//                same super-node. They're entry points to the sub-graph;
//                for each, we list every PARENT in the full lineage that
//                lives OUTSIDE the super-node (`inbound_external`).
//   descendants = members with NO outgoing edges to other members of the
//                same super-node. They're exit points; for each, we list
//                every CHILD outside the super-node (`outbound_external`).
//
// The full-graph JSON (already prefetched into cache.full) carries the
// per-entity `selectors` membership and all the lineage edges, so the
// report is a pure client-side computation — no extra round-trips.
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

  // Build adjacency from the lineage edges. Two maps because we need both
  // directions and the JSON only stores edges as (source, target) pairs.
  const parentsOf = new Map();
  const childrenOf = new Map();
  for (const e of fullData.elements) {
    if (e.data.kind !== "lineage") continue;
    const { source, target } = e.data;
    (parentsOf.get(target) || parentsOf.set(target, []).get(target)).push(source);
    (childrenOf.get(source) || childrenOf.set(source, []).get(source)).push(target);
  }

  const labelOf = new Map();
  for (const e of fullData.elements) {
    if (e.data.kind === "entity") labelOf.set(e.data.id, e.data.label || e.data.id);
  }

  // Same semantics as classify_boundary() in sdag.py:
  //   inbound  := has external parents OR no internal parents
  //   outbound := has external children OR no internal children
  // A member can appear in both lists.
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
        label: labelOf.get(uid) || uid,
        uid,
        inbound_external: externalParents.map((p) => labelOf.get(p) || p).sort(),
      });
    }
    if (externalChildren.length > 0 || internalChildren.length === 0) {
      descendants.push({
        label: labelOf.get(uid) || uid,
        uid,
        outbound_external: externalChildren.map((c) => labelOf.get(c) || c).sort(),
      });
    }
  }
  ancestors.sort((a, b) => a.label.localeCompare(b.label));
  descendants.sort((a, b) => a.label.localeCompare(b.label));
  return { superName, members: members.size, ancestors, descendants };
}

function renderBoundaryReport(report) {
  // Plain text, multi-line, monospace. Easier to scan than nested JSON when
  // some descendants might have 20+ outbound models, and copies cleanly out
  // of the panel into a notebook / ticket.
  if (!report) {
    document.getElementById("detail-body").textContent = "click a node…";
    return;
  }
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
  document.getElementById("detail-body").textContent = out.join("\n");
}

function clearDetail() {
  document.getElementById("detail-body").textContent = "click a node…";
}

function buildLegend() {
  const wrap = document.getElementById("legend");
  // Resource-type swatches: always visible.
  for (const [kind, colour] of Object.entries(RESOURCE_COLOURS)) {
    const row = document.createElement("div");
    row.className = "flex items-center gap-2";
    row.innerHTML = `
      <span style="background:${colour}" class="inline-block w-3 h-3 rounded-sm"></span>
      <span class="text-slate-300">${kind}</span>`;
    wrap.appendChild(row);
  }
  // Filter-only legend: boundary colours + halo colours. Visibility is
  // toggled by setFilterLegendVisible() when the dropdown changes.
  const filterLegend = document.createElement("div");
  filterLegend.id = "filter-legend";
  filterLegend.className = "mt-2 pt-2 border-t border-slate-700 space-y-1 hidden";
  filterLegend.innerHTML = `
    <div class="text-slate-400 uppercase tracking-wider text-[10px]">when filtered</div>
    <div class="flex items-center gap-2">
      <span style="background:#10b981" class="inline-block w-3 h-3 rounded-sm"></span>
      <span class="text-slate-300">inbound boundary</span>
    </div>
    <div class="flex items-center gap-2">
      <span style="background:#f59e0b" class="inline-block w-3 h-3 rounded-sm"></span>
      <span class="text-slate-300">outbound boundary</span>
    </div>
    <div class="flex items-center gap-2">
      <span style="background:#f43f5e" class="inline-block w-3 h-3 rounded-sm"></span>
      <span class="text-slate-300">both (in &amp; out)</span>
    </div>
    <div class="flex items-center gap-2">
      <span style="background:#334155" class="inline-block w-3 h-3 rounded-sm"></span>
      <span class="text-slate-300">halo upstream</span>
    </div>
    <div class="flex items-center gap-2">
      <span style="background:#3b3651" class="inline-block w-3 h-3 rounded-sm"></span>
      <span class="text-slate-300">halo downstream</span>
    </div>`;
  wrap.appendChild(filterLegend);
}

function setFilterLegendVisible(visible) {
  const el = document.getElementById("filter-legend");
  if (el) el.classList.toggle("hidden", !visible);
}

// ─────────────────────────────────────────────────────────────────────────
// Wire up
// ─────────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  renderBuildBanner();
  buildLegend();
  document.getElementById("btn-full" ).addEventListener("click", () => showView("full"));
  document.getElementById("btn-super").addEventListener("click", () => showView("super"));
  document.getElementById("btn-fit"   ).addEventListener("click", () => cy && cy.fit());
  document.getElementById("btn-relayout").addEventListener("click", () => {
    if (cy) runLayout(currentView, document.getElementById("status"));
  });
  document.getElementById("filter-selector").addEventListener("change", (e) => {
    currentFilter = e.target.value;
    setFilterLegendVisible(currentFilter !== "__all__");
    // Auto-switch to full view when filtering — the filter is a no-op in
    // super view, and the user almost certainly wants to see the lineage.
    if (currentFilter !== "__all__" && currentView !== "full") {
      showView("full");  // showView calls applyFilter() + syncUrl()
      return;
    }
    rerunWithFilter();
    syncUrl();  // rerunWithFilter() doesn't go through showView(), so sync here
  });

  // Back/Forward: re-apply the view+filter encoded in the URL the browser
  // just navigated to. suppressUrlSync stops the resulting re-render from
  // pushing a fresh entry (which would undo the navigation we're reacting to).
  window.addEventListener("popstate", async () => {
    suppressUrlSync = true;
    try {
      const view = applyStateFromUrl();
      await showView(view);
    } finally {
      suppressUrlSync = false;
    }
  });

  // Pre-fetch the full graph so the dropdown is populated up front, then
  // restore view + filter from the URL (deep link) before the first render.
  try {
    await fetchView("full");
    populateFilterDropdown(cache.full);

    // Restore state from the query string (validated against the dropdown),
    // then normalise the landing URL with replaceState so the first history
    // entry is canonical — no duplicate to click Back through. showView()'s
    // own syncUrl() is then a no-op (the URL already matches).
    const initialView = applyStateFromUrl();
    currentView = initialView;
    const normalised = canonicalUrl();
    if (normalised !== currentUrl()) {
      window.history.replaceState(null, "", normalised);
    }
    await showView(initialView);
  } catch (e) {
    document.getElementById("status").textContent = `error: ${e.message}`;
    console.error(e);
  }
});
