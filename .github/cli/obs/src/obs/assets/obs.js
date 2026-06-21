/* obs viewer — vanilla-JS SPA, no build step.
 *
 * Two URL-routed views:
 *   obs.html            → overview: a Plotly scatter of every run (time × duration,
 *                         coloured pass/fail). Click a point → that run's detail.
 *   obs.html?run=<id>   → detail: the run's thread-grouped Gantt (full-width SVG) with a
 *                         time-brush to zoom the window; bars are always labelled.
 *
 * Branding: design-tokens.json carries THREE brand packs, each light+dark. obs.js injects
 * the active brand+theme `chrome` palette onto CSS variables, and feeds the `plotly` +
 * `gantt` palettes to the canvases (which can't read CSS vars).
 *
 * Templated tokens (substituted by gantt.py at write time):
 *   BUILD_ID = {{BUILD_ID}}
 *   SOURCE   = {{SOURCE}}
 */
(() => {
  "use strict";

  const BUILD_ID = "{{BUILD_ID}}";
  const SOURCE = "{{SOURCE}}";
  const SVG_NS = "http://www.w3.org/2000/svg";
  const THEME_KEY = "obs-theme";
  const BRAND_KEY = "obs-brand";
  const SIDEBAR_KEY = "obs-sidebar";
  const URL_PARAM_RUN = "run";

  const FALLBACK_TOKENS = {
    defaultBrand: "freshgreens",
    resourceColours: { model: "#3b82f6", test: "#a855f7", _fallback: "#94a3b8" },
    statusColours: { success: "#10b981", error: "#ef4444", _fallback: "#94a3b8" },
    brands: {
      freshgreens: {
        name: "obs", tagline: "dbt run telemetry",
        fonts: { sans: '"Poppins", ui-sans-serif, system-ui, sans-serif', mono: "ui-monospace, monospace" },
        themes: {
          dark: { toggleLabel: "☽ Dark",
            chrome: { canvas: "#242C30", appBg: "#242C30", sidebarBg: "#2D373D", panelBg: "#3A474E", panelHover: "#4B5C65",
              border: "#4B5C65", borderSoft: "#3A474E", textStrong: "#F1F3F3", text: "#E3E6E7", textSecondary: "#C7CDD0",
              textMuted: "#ACB5B9", accent: "#A5C84D", accentText: "#B8D666", onAccent: "#1B2125", okText: "#6EE7B7",
              warnText: "#FCD34D", failText: "#FCA5A5", tooltipBg: "rgba(20,26,29,0.96)", shadow: "rgba(0,0,0,0.45)" },
            plotly: { paper: "#242C30", plot: "#2D373D", font: "#E3E6E7", grid: "#3A474E", axisLine: "#4B5C65",
              markerPass: "#6EE7B7", markerFail: "#FCA5A5", markerLine: "#242C30", hoverBg: "#1B2125", hoverBorder: "#4B5C65", accent: "#A5C84D" },
            gantt: { laneBandA: "#242C30", laneBandB: "#2D373D", grid: "#3A474E", axisText: "#ACB5B9", barStroke: "rgba(0,0,0,0.40)" } },
          light: { toggleLabel: "☼ Light",
            chrome: { canvas: "#EDEFF0", appBg: "#E4E7E8", sidebarBg: "#FFFFFF", panelBg: "#F1F3F4", panelHover: "#E2E5E7",
              border: "#C2C8CB", borderSoft: "#DDE0E2", textStrong: "#1B2125", text: "#28323A", textSecondary: "#3A474E",
              textMuted: "#56656D", accent: "#A5C84D", accentText: "#46630F", onAccent: "#1B2125", okText: "#0D6B30",
              warnText: "#B45309", failText: "#C2151B", tooltipBg: "rgba(255,255,255,0.97)", shadow: "rgba(60,72,80,0.22)" },
            plotly: { paper: "#FFFFFF", plot: "#F1F3F4", font: "#28323A", grid: "#DDE0E2", axisLine: "#C2C8CB",
              markerPass: "#0D6B30", markerFail: "#C2151B", markerLine: "#FFFFFF", hoverBg: "#FFFFFF", hoverBorder: "#C2C8CB", accent: "#46630F" },
            gantt: { laneBandA: "#FFFFFF", laneBandB: "#F1F3F4", grid: "#DDE0E2", axisText: "#56656D", barStroke: "rgba(27,33,37,0.18)" } },
        },
      },
    },
  };

  // chrome token key → CSS custom property.
  const CHROME_VARS = {
    canvas: "--canvas", appBg: "--app-bg", sidebarBg: "--sidebar-bg", panelBg: "--panel-bg", panelHover: "--panel-hover",
    border: "--border", borderSoft: "--border-soft", textStrong: "--text-strong", text: "--text",
    textSecondary: "--text-secondary", textMuted: "--text-muted", accent: "--accent", accentText: "--accent-text",
    onAccent: "--on-accent", okText: "--ok-text", warnText: "--warn-text", failText: "--fail-text",
    tooltipBg: "--tooltip-bg", shadow: "--shadow",
  };

  const MARGIN = { top: 44, right: 28, bottom: 12, left: 156 };
  const LANE_H = 46, BAR_H = 26;
  const TICK_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600];

  const state = {
    tokens: FALLBACK_TOKENS,
    index: [],
    bundleMeta: {},
    runsCache: new Map(),
    data: null,
    currentRunId: null,
    currentView: "overview",
    currentBrand: "freshgreens",
    currentTheme: document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark",
    colourBy: "resource",
    viewStart: 0,
    viewEnd: null, // null ⇒ full wall window
  };

  const $ = (id) => document.getElementById(id);
  const svgEl = (tag, attrs) => {
    const e = document.createElementNS(SVG_NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  };
  const stripMeta = (obj) => Object.fromEntries(Object.entries(obj || {}).filter(([k]) => !k.startsWith("_")));

  const brand = () => state.tokens.brands[state.currentBrand] || FALLBACK_TOKENS.brands.freshgreens;
  const theme = () => brand().themes[state.currentTheme] || brand().themes.dark;
  const plotlyPalette = () => theme().plotly;
  const ganttPalette = () => theme().gantt;

  const resourceColour = (rt) =>
    (state.tokens.resourceColours || {})[rt] || (state.tokens.resourceColours || {})._fallback || "#94a3b8";
  const statusColour = (s) =>
    (state.tokens.statusColours || {})[(s || "").toLowerCase()] || (state.tokens.statusColours || {})._fallback || "#94a3b8";
  const isOk = (s) => ["success", "pass"].includes((s || "").toLowerCase());
  const barFill = (n) => (state.colourBy === "status" ? statusColour(n.status) : resourceColour(n.resource_type));

  const fmtClock = (iso) => new Date(iso).toLocaleTimeString("en-GB", { hour12: false, timeZone: "UTC" });
  const fmtDur = (s) => (s >= 1 ? s.toFixed(2) + "s" : (s * 1000).toFixed(0) + "ms");
  const hasRun = (id) => state.index.some((e) => e.invocation_id === id);

  // ── Brand + theme provider ───────────────────────────────────────────────────
  function applyBrandTheme({ persist = true } = {}) {
    const t = theme();
    const root = document.documentElement;
    root.setAttribute("data-theme", state.currentTheme);
    for (const [k, cssVar] of Object.entries(CHROME_VARS)) {
      if (t.chrome && t.chrome[k]) root.style.setProperty(cssVar, t.chrome[k]);
    }
    const f = brand().fonts || {};
    if (f.sans) root.style.setProperty("--obs-font-sans", f.sans);
    if (f.mono) root.style.setProperty("--obs-font-mono", f.mono);
    $("brand-name").textContent = brand().name || "obs";
    $("brand-tagline").textContent = brand().tagline || "";
    $("btn-theme").textContent = t.toggleLabel || (state.currentTheme === "dark" ? "☽ Dark" : "☼ Light");
    if (persist) {
      try { localStorage.setItem(THEME_KEY, state.currentTheme); localStorage.setItem(BRAND_KEY, state.currentBrand); } catch (e) { /* private mode */ }
    }
    if (state.currentView === "overview") renderOverview();
    else if (state.data) render();
  }
  const toggleTheme = () => { state.currentTheme = state.currentTheme === "dark" ? "light" : "dark"; applyBrandTheme(); };
  function setBrand(id) {
    if (!state.tokens.brands[id]) return;
    state.currentBrand = id;
    $("brand-picker").value = id;
    applyBrandTheme();
  }

  // ── URL routing ───────────────────────────────────────────────────────────────
  const currentUrl = () => `${location.pathname}${location.search}${location.hash}`;
  function navigate(runId) {
    const params = new URLSearchParams(location.search);
    if (runId) params.set(URL_PARAM_RUN, runId);
    else params.delete(URL_PARAM_RUN);
    const qs = params.toString();
    const next = `${location.pathname}${qs ? `?${qs}` : ""}${location.hash}`;
    if (next !== currentUrl()) history.pushState(null, "", next);
    applyRoute(runId);
  }
  async function applyRoute(runId) {
    if (runId && hasRun(runId)) {
      state.currentView = "detail";
      document.body.dataset.view = "detail";
      setNavActive("detail");
      await selectRun(runId);
    } else {
      state.currentView = "overview";
      document.body.dataset.view = "overview";
      setNavActive("overview");
      renderOverview();
    }
  }
  function setNavActive(view) {
    $("nav-overview").classList.toggle("is-active", view === "overview");
    $("nav-detail").classList.toggle("is-active", view === "detail");
  }

  // ── Overview: Plotly scatter ──────────────────────────────────────────────────
  function renderOverview() {
    const pp = plotlyPalette();
    const sans = (brand().fonts && brand().fonts.sans) || "sans-serif";
    const build = (entries, colour, name) => {
      const sz = (e) => 8 + 2.4 * Math.sqrt(e.configured_threads || e.observed_threads || 1);
      return {
        x: entries.map((e) => e.run_started_at),
        y: entries.map((e) => e.wall_secs),
        customdata: entries.map((e) => e.invocation_id),
        text: entries.map(
          (e) =>
            `${e.command || "?"} · ${e.configured_threads ?? e.observed_threads} threads<br>` +
            `${e.n_nodes} nodes · ${e.wall_secs.toFixed(1)}s wall<br>${e.run_started_at}`
        ),
        mode: "markers",
        type: "scatter",
        name,
        marker: { color: colour, size: entries.map(sz), line: { color: pp.markerLine, width: 1 }, opacity: 0.9 },
        hovertemplate: "%{text}<extra></extra>",
      };
    };
    const passed = state.index.filter((e) => !e.has_failures);
    const failed = state.index.filter((e) => e.has_failures);
    const layout = {
      paper_bgcolor: pp.paper,
      plot_bgcolor: pp.plot,
      font: { color: pp.font, family: sans, size: 12 },
      margin: { l: 64, r: 128, t: 16, b: 48 },
      showlegend: true,
      // In the right gutter (outside the plotting area) so it never overlaps — or
      // intercepts clicks on — data points.
      legend: { x: 1.02, y: 1, xanchor: "left", yanchor: "top", bgcolor: "rgba(0,0,0,0)", font: { color: pp.font, family: sans } },
      hoverlabel: { bgcolor: pp.hoverBg, bordercolor: pp.hoverBorder, font: { color: pp.font, family: sans } },
      xaxis: { title: { text: "run start (UTC)" }, type: "date", gridcolor: pp.grid, linecolor: pp.axisLine, zeroline: false },
      yaxis: { title: { text: "duration — wall seconds" }, gridcolor: pp.grid, linecolor: pp.axisLine, zeroline: false, rangemode: "tozero" },
    };
    const config = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] };
    const div = $("scatter");
    window.Plotly.react(div, [build(passed, pp.markerPass, "passed"), build(failed, pp.markerFail, "has failures")], layout, config);
    if (!div._obsClickBound) {
      div.on("plotly_click", (ev) => {
        const id = ev.points && ev.points[0] && ev.points[0].customdata;
        if (id) navigate(id);
      });
      div._obsClickBound = true;
    }
    const nFail = failed.length;
    $("overview-stats").textContent = [
      `runs    ${state.index.length}`,
      `window  ${state.bundleMeta.days != null ? state.bundleMeta.days + "d" : "—"}`,
      `passed  ${state.index.length - nFail}`,
      `failed  ${nFail}`,
    ].join("\n");
    $("status").textContent = `${state.index.length} runs`;
  }

  // ── Detail: full-width SVG Gantt with a time-brush viewport ────────────────────
  function chooseStep(windowSecs, innerW) {
    const target = Math.max(windowSecs / Math.max(innerW / 92, 2), 0.001);
    return TICK_STEPS.find((s) => s >= target) || TICK_STEPS[TICK_STEPS.length - 1];
  }

  function render() {
    const d = state.data;
    if (!d) return;
    const p = ganttPalette();
    const { threads, nodes } = d;
    const wallSecs = d.metadata.wall_secs || 0.001;
    const v0 = state.viewStart;
    const v1 = state.viewEnd == null ? wallSecs : state.viewEnd;
    const win = Math.max(v1 - v0, 0.001);

    const scroll = $("chart-scroll");
    const totalW = Math.max(scroll.clientWidth || 900, MARGIN.left + 160);
    const innerW = totalW - MARGIN.left - MARGIN.right;
    const plotX0 = MARGIN.left;
    const plotX1 = MARGIN.left + innerW;
    const laneIndex = new Map(threads.map((t, i) => [t, i]));
    const height = MARGIN.top + threads.length * LANE_H + MARGIN.bottom;
    const xAt = (off) => MARGIN.left + ((off - v0) / win) * innerW;
    const clampX = (x) => Math.max(plotX0, Math.min(plotX1, x));
    const laneY = (t) => MARGIN.top + laneIndex.get(t) * LANE_H;

    const svg = svgEl("svg", { width: totalW, height, viewBox: `0 0 ${totalW} ${height}` });
    const defs = svgEl("defs", {});
    svg.appendChild(defs);

    threads.forEach((t, i) => {
      svg.appendChild(svgEl("rect", { x: plotX0, y: MARGIN.top + i * LANE_H, width: innerW, height: LANE_H, fill: i % 2 ? p.laneBandB : p.laneBandA }));
      const label = svgEl("text", { x: plotX0 - 10, y: MARGIN.top + i * LANE_H + LANE_H / 2 + 4, "text-anchor": "end", fill: p.axisText, "font-size": "12", "font-family": "var(--obs-font-mono)" });
      label.textContent = t;
      svg.appendChild(label);
    });

    const step = chooseStep(win, innerW);
    const wallStartMs = new Date(d.metadata.wall_start).getTime();
    const firstTick = Math.ceil(v0 / step) * step;
    for (let s = firstTick; s <= v1 + 1e-6; s += step) {
      const x = xAt(s);
      svg.appendChild(svgEl("line", { x1: x, y1: MARGIN.top, x2: x, y2: height - MARGIN.bottom, stroke: p.grid, "stroke-width": 1 }));
      const lbl = svgEl("text", { x, y: MARGIN.top - 16, "text-anchor": "middle", fill: p.axisText, "font-size": "10", "font-family": "var(--obs-font-mono)" });
      lbl.textContent = fmtClock(new Date(wallStartMs + s * 1000).toISOString());
      svg.appendChild(lbl);
      const off = svgEl("text", { x, y: MARGIN.top - 4, "text-anchor": "middle", fill: p.axisText, "font-size": "9", "font-family": "var(--obs-font-mono)" });
      off.textContent = "+" + (Math.round(s * 10) / 10) + "s";
      svg.appendChild(off);
    }

    const barPad = (LANE_H - BAR_H) / 2;
    nodes.forEach((n, i) => {
      const startOff = n.start_offset_secs;
      const endOff = startOff + n.duration_secs;
      if (endOff < v0 || startOff > v1) return; // outside the brushed window
      const rawX0 = xAt(startOff);
      const x0 = clampX(rawX0);
      const x1 = clampX(xAt(endOff));
      const w = Math.max(x1 - x0, 2);
      const y = laneY(n.thread_id) + barPad;
      const g = svgEl("g", {});
      const rect = svgEl("rect", { class: "bar", x: x0, y, width: w, height: BAR_H, rx: 3, fill: barFill(n),
        stroke: isOk(n.status) ? p.barStroke : "#ef4444", "stroke-width": isOk(n.status) ? 0.5 : 2, style: "cursor:pointer" });
      rect.addEventListener("mousemove", (e) => showTip(e, n));
      rect.addEventListener("mouseleave", hideTip);
      g.appendChild(rect);
      // Always-on label, clipped to the bar so it never overflows; white fill + dark
      // outline (paint-order) keeps it legible on any resource colour.
      const clipId = `clab-${i}`;
      const clip = svgEl("clipPath", { id: clipId });
      clip.appendChild(svgEl("rect", { x: x0, y, width: w, height: BAR_H, rx: 3 }));
      defs.appendChild(clip);
      const label = svgEl("text", { x: rawX0 + 5, y: y + BAR_H / 2 + 4, "font-size": "10", "font-family": "var(--obs-font-sans)",
        fill: "#ffffff", stroke: "rgba(0,0,0,0.55)", "stroke-width": "2.5", "paint-order": "stroke", "pointer-events": "none", "clip-path": `url(#${clipId})` });
      label.textContent = n.name;
      g.appendChild(label);
      svg.appendChild(g);
    });

    $("chart").replaceChildren(svg);
  }

  // Tooltip
  function showTip(evt, n) {
    const el = $("tooltip");
    el.textContent = `${n.node_id}\nthread    ${n.thread_id}\nstatus    ${n.status}\n` +
      `start     ${fmtClock(n.start)} UTC  (+${n.start_offset_secs.toFixed(2)}s)\nduration  ${fmtDur(n.duration_secs)}`;
    el.style.display = "block";
    moveTip(evt);
  }
  function moveTip(evt) {
    const el = $("tooltip"), pad = 14, r = el.getBoundingClientRect();
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + r.width > window.innerWidth) x = evt.clientX - r.width - pad;
    if (y + r.height > window.innerHeight) y = evt.clientY - r.height - pad;
    el.style.left = x + "px";
    el.style.top = y + "px";
  }
  const hideTip = () => ($("tooltip").style.display = "none");

  // ── Time-brush ────────────────────────────────────────────────────────────────
  function resetBrush() {
    state.viewStart = 0;
    state.viewEnd = null;
    $("brush-start").value = "0";
    $("brush-end").value = "1000";
    updateBrushUi();
  }
  function updateBrushUi() {
    const wallSecs = (state.data && state.data.metadata.wall_secs) || 0;
    const a = Number($("brush-start").value), b = Number($("brush-end").value);
    const lo = Math.min(a, b), hi = Math.max(a, b);
    const fill = $("brush-fill");
    fill.style.left = lo / 10 + "%";
    fill.style.width = (hi - lo) / 10 + "%";
    if (state.data) {
      const startMs = new Date(state.data.metadata.wall_start).getTime();
      const t0 = (lo / 1000) * wallSecs, t1 = (hi / 1000) * wallSecs;
      $("brush-readout").textContent =
        `${fmtClock(new Date(startMs + t0 * 1000).toISOString())} → ${fmtClock(new Date(startMs + t1 * 1000).toISOString())}  ·  ${(t1 - t0).toFixed(1)}s of ${wallSecs.toFixed(1)}s`;
    }
  }
  function onBrush() {
    const wallSecs = (state.data && state.data.metadata.wall_secs) || 0;
    let a = Number($("brush-start").value), b = Number($("brush-end").value);
    if (b - a < 10) { // keep a minimum 1% window
      if (document.activeElement === $("brush-start")) a = Math.max(0, b - 10);
      else b = Math.min(1000, a + 10);
      $("brush-start").value = String(a);
      $("brush-end").value = String(b);
    }
    const lo = Math.min(a, b), hi = Math.max(a, b);
    state.viewStart = (lo / 1000) * wallSecs;
    state.viewEnd = (hi / 1000) * wallSecs;
    updateBrushUi();
    render();
  }

  // ── Sidebar panels ────────────────────────────────────────────────────────────
  function renderLegend() {
    const body = $("legend-body");
    const entries = state.colourBy === "status"
      ? Object.entries(stripMeta(state.tokens.statusColours))
      : Object.entries(stripMeta(state.tokens.resourceColours));
    const present = state.data
      ? new Set(state.data.nodes.map((n) => (state.colourBy === "status" ? n.status.toLowerCase() : n.resource_type)))
      : null;
    body.replaceChildren();
    entries.filter(([k]) => !present || present.has(k)).forEach(([label, colour]) => {
      const row = document.createElement("div");
      row.className = "legend-item";
      row.innerHTML = `<span class="swatch" style="background:${colour}"></span><span>${label}</span>`;
      body.appendChild(row);
    });
  }
  function renderStats() {
    const m = state.data.metadata;
    $("metadata-body").textContent = [
      `invocation ${m.invocation_id.slice(0, 8)}`,
      `nodes      ${m.n_nodes}`,
      `threads    ${m.n_threads}`,
      `wall       ${m.wall_secs.toFixed(1)}s`,
      `cpu        ${m.cpu_secs.toFixed(1)}s`,
    ].join("\n");
    const longest = [...state.data.nodes].sort((a, b) => b.duration_secs - a.duration_secs).slice(0, 6);
    $("detail-body").textContent = longest.map((n) => `${n.duration_secs.toFixed(2).padStart(7)}s  ${n.name}`).join("\n");
  }
  function renderLogs() {
    const nodes = state.data.nodes;
    const ordered = [...nodes].sort((a, b) => a.start_offset_secs - b.start_offset_secs);
    $("run-logs-summary").textContent = `Run logs — ${nodes.length} nodes (execution order)`;
    const body = $("run-logs-body");
    body.replaceChildren();
    for (const n of ordered) {
      const row = document.createElement("div");
      if (!isOk(n.status)) row.className = "log-fail";
      const dur = (n.duration_secs.toFixed(2) + "s").padStart(8);
      const st = (n.status || "").toUpperCase().padEnd(8);
      const msg = n.message ? "  " + String(n.message).replace(/\s+/g, " ").trim() : "";
      row.textContent = `${fmtClock(n.start)}  ${dur}  ${st} ${n.node_id}${msg}`;
      body.appendChild(row);
    }
  }

  function renderRunMeta() {
    const e = state.index.find((r) => r.invocation_id === state.currentRunId);
    if (!e) { $("run-meta").textContent = ""; return; }
    const cfg = e.configured_threads != null ? `${e.configured_threads}t configured` : `${e.observed_threads}t observed`;
    $("run-meta").textContent = `${e.command || "?"} · ${cfg}\n${e.git_sha ? e.git_sha.slice(0, 7) + " · " : ""}${e.has_failures ? "has failures" : "all passed"}`;
  }

  // ── Run picker ──────────────────────────────────────────────────────────────────
  function runLabel(e) {
    const t = new Date(e.run_started_at).toLocaleTimeString("en-GB", { hour12: false, timeZone: "UTC" });
    const cfg = e.configured_threads != null ? e.configured_threads : e.observed_threads;
    return `${t} · ${e.command || "?"} · ${cfg}t · ${e.n_nodes}n${e.has_failures ? " ⚠" : ""}`;
  }
  function populatePicker() {
    const picker = $("run-picker");
    picker.replaceChildren();
    const byDay = new Map();
    for (const e of state.index) {
      const day = new Date(e.run_started_at).toISOString().slice(0, 10);
      if (!byDay.has(day)) byDay.set(day, []);
      byDay.get(day).push(e);
    }
    for (const [day, runs] of byDay) {
      const group = document.createElement("optgroup");
      group.label = `${day}  (${runs.length})`;
      for (const e of runs) {
        const opt = document.createElement("option");
        opt.value = e.invocation_id;
        opt.textContent = runLabel(e);
        group.appendChild(opt);
      }
      picker.appendChild(group);
    }
    picker.addEventListener("change", () => navigate(picker.value));
  }

  async function selectRun(invocationId) {
    state.currentRunId = invocationId;
    $("run-picker").value = invocationId;
    $("status").textContent = "loading run…";
    let payload = state.runsCache.get(invocationId);
    if (!payload) {
      try {
        const resp = await fetch(`runs/${invocationId}.json?v=${BUILD_ID}`, { cache: "no-store" });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        payload = await resp.json();
        state.runsCache.set(invocationId, payload);
      } catch (err) {
        $("status").textContent = "error: " + err.message;
        return;
      }
    }
    state.data = payload;
    const m = payload.metadata;
    $("status").textContent = `${m.n_nodes} nodes · ${m.n_threads} threads`;
    renderRunMeta();
    renderStats();
    renderLegend();
    renderLogs();
    resetBrush();
    render();
  }

  // ── Sidebar collapse ────────────────────────────────────────────────────────────
  function setCollapsed(c) {
    $("app-root").classList.toggle("sidebar-collapsed", c);
    $("btn-sidebar-toggle").textContent = c ? "⟩" : "⟨";
    try { localStorage.setItem(SIDEBAR_KEY, c ? "1" : "0"); } catch (e) { /* private mode */ }
    requestAnimationFrame(() => {
      if (state.currentView === "overview" && window.Plotly) window.Plotly.Plots.resize($("scatter"));
      else if (state.data) render();
    });
  }

  // ── Boot ──────────────────────────────────────────────────────────────────────
  async function boot() {
    try {
      const resp = await fetch(`design-tokens.json?v=${BUILD_ID}`, { cache: "no-store" });
      if (resp.ok) state.tokens = await resp.json();
    } catch (_e) { /* keep fallbacks */ }

    // Resolve the active brand: saved → default → first available.
    const brandIds = Object.keys(state.tokens.brands || FALLBACK_TOKENS.brands);
    let savedBrand = null;
    try { savedBrand = localStorage.getItem(BRAND_KEY); } catch (e) { /* private mode */ }
    state.currentBrand = brandIds.includes(savedBrand) ? savedBrand
      : (brandIds.includes(state.tokens.defaultBrand) ? state.tokens.defaultBrand : brandIds[0]);

    const picker = $("brand-picker");
    picker.replaceChildren();
    for (const id of brandIds) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = (state.tokens.brands[id] && state.tokens.brands[id].name) || id;
      picker.appendChild(opt);
    }
    picker.value = state.currentBrand;
    picker.addEventListener("change", () => setBrand(picker.value));

    $("build-banner").textContent = `build ${BUILD_ID}\n${SOURCE}`;
    applyBrandTheme({ persist: false });
    setCollapsed(localStorage.getItem(SIDEBAR_KEY) === "1");

    // Controls
    $("btn-theme").addEventListener("click", toggleTheme);
    $("btn-sidebar-toggle").addEventListener("click", () => setCollapsed(!$("app-root").classList.contains("sidebar-collapsed")));
    $("nav-overview").addEventListener("click", () => navigate(null));
    $("nav-detail").addEventListener("click", () => navigate(state.currentRunId || (state.index[0] && state.index[0].invocation_id)));
    document.querySelectorAll("#colour-seg button").forEach((b) =>
      b.addEventListener("click", () => {
        state.colourBy = b.dataset.mode;
        document.querySelectorAll("#colour-seg button").forEach((x) => x.classList.toggle("is-active", x === b));
        renderLegend();
        render();
      })
    );
    document.querySelector('#colour-seg button[data-mode="resource"]').classList.add("is-active");
    $("brush-start").addEventListener("input", onBrush);
    $("brush-end").addEventListener("input", onBrush);
    $("brush-reset").addEventListener("click", () => { resetBrush(); render(); });
    window.addEventListener("popstate", () => applyRoute(new URLSearchParams(location.search).get(URL_PARAM_RUN)));

    // Keep the full-width Gantt fitted to the container.
    if (window.ResizeObserver) {
      new ResizeObserver(() => { if (state.currentView === "detail" && state.data) render(); }).observe($("chart-scroll"));
    }

    // Load the run index.
    try {
      const resp = await fetch(`index.json?v=${BUILD_ID}`, { cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status} fetching index.json`);
      const doc = await resp.json();
      state.index = doc.index || [];
      state.bundleMeta = doc.metadata || {};
    } catch (err) {
      $("status").textContent = "error: " + err.message;
      return;
    }
    if (state.index.length === 0) { $("status").textContent = "no runs in window"; return; }
    populatePicker();
    await applyRoute(new URLSearchParams(location.search).get(URL_PARAM_RUN));
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
