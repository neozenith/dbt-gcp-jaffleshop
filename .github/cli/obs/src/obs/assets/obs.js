/* obs viewer — vanilla-JS SPA, no build step.
 *
 * Two routes, URL-driven (deep-linkable, Back/Forward aware):
 *   obs.html            → overview: a Plotly scatter of every run (time × duration,
 *                         coloured pass/fail). Click a point → that run's detail.
 *   obs.html?run=<id>   → detail: the run's thread-grouped Gantt (SVG).
 *
 * Loads design-tokens.json for the CANVAS palettes (Plotly + the SVG Gantt can't read
 * the CSS variables that theme the chrome), index.json for the run list, and
 * runs/<id>.json lazily per selected run.
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
  const SIDEBAR_KEY = "obs-sidebar";
  const ZOOM_KEY = "obs.zoom";
  const URL_PARAM_RUN = "run";

  const FALLBACK_TOKENS = {
    brand: { name: "obs", tagline: "dbt run telemetry" },
    resourceColours: { model: "#3b82f6", test: "#a855f7", _fallback: "#94a3b8" },
    statusColours: { success: "#10b981", error: "#ef4444", _fallback: "#94a3b8" },
    themes: {
      dark: { toggleLabel: "☽ Dark", laneBandA: "#242C30", laneBandB: "#2D373D", grid: "#3A474E",
        axisText: "#ACB5B9", barStroke: "rgba(0,0,0,0.40)",
        plotly: { paper: "#242C30", plot: "#2D373D", font: "#E3E6E7", grid: "#3A474E", axisLine: "#4B5C65",
          markerPass: "#6EE7B7", markerFail: "#FCA5A5", markerLine: "#242C30", hoverBg: "#1B2125",
          hoverBorder: "#4B5C65", accent: "#A5C84D" } },
      light: { toggleLabel: "☼ Light", laneBandA: "#FFFFFF", laneBandB: "#F1F3F4", grid: "#DDE0E2",
        axisText: "#56656D", barStroke: "rgba(27,33,37,0.18)",
        plotly: { paper: "#FFFFFF", plot: "#F1F3F4", font: "#28323A", grid: "#DDE0E2", axisLine: "#C2C8CB",
          markerPass: "#0D6B30", markerFail: "#C2151B", markerLine: "#FFFFFF", hoverBg: "#FFFFFF",
          hoverBorder: "#C2C8CB", accent: "#46630F" } },
    },
  };

  const MARGIN = { top: 44, right: 28, bottom: 28, left: 156 };
  const LANE_H = 46, BAR_H = 26;
  const TICK_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600];

  const state = {
    tokens: FALLBACK_TOKENS,
    index: [],
    runsCache: new Map(),
    data: null,
    currentRunId: null,
    currentView: "overview",
    currentTheme: document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark",
    pxPerSec: 14,
    colourBy: "resource",
    showLabels: false,
  };

  const $ = (id) => document.getElementById(id);
  const svgEl = (tag, attrs) => {
    const e = document.createElementNS(SVG_NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  };
  const stripMeta = (obj) => Object.fromEntries(Object.entries(obj || {}).filter(([k]) => !k.startsWith("_")));
  const palette = () => state.tokens.themes[state.currentTheme] || FALLBACK_TOKENS.themes.dark;
  const plotlyPalette = () => palette().plotly;

  const resourceColour = (rt) =>
    (state.tokens.resourceColours || {})[rt] || (state.tokens.resourceColours || {})._fallback || "#94a3b8";
  const statusColour = (s) =>
    (state.tokens.statusColours || {})[(s || "").toLowerCase()] || (state.tokens.statusColours || {})._fallback || "#94a3b8";
  const isOk = (s) => ["success", "pass"].includes((s || "").toLowerCase());
  const barFill = (n) => (state.colourBy === "status" ? statusColour(n.status) : resourceColour(n.resource_type));

  const fmtClock = (iso) => new Date(iso).toLocaleTimeString("en-GB", { hour12: false, timeZone: "UTC" });
  const fmtDur = (s) => (s >= 1 ? s.toFixed(2) + "s" : (s * 1000).toFixed(0) + "ms");
  const niceStep = (pps) => TICK_STEPS.find((s) => s * pps >= 72) || TICK_STEPS[TICK_STEPS.length - 1];
  const hasRun = (id) => state.index.some((e) => e.invocation_id === id);

  // ── Theme provider ─────────────────────────────────────────────────────────
  function applyTheme(theme, { persist = true } = {}) {
    state.currentTheme = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", state.currentTheme);
    if (persist) {
      try { localStorage.setItem(THEME_KEY, state.currentTheme); } catch (e) { /* private mode */ }
    }
    const btn = $("btn-theme");
    if (btn) btn.textContent = palette().toggleLabel || (state.currentTheme === "dark" ? "☽ Dark" : "☼ Light");
    // Re-paint whichever canvas is live (both carry colours that aren't CSS vars).
    if (state.currentView === "overview") renderOverview();
    else if (state.data) render();
  }
  const toggleTheme = () => applyTheme(state.currentTheme === "dark" ? "light" : "dark");

  // ── URL routing ─────────────────────────────────────────────────────────────
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
    $("nav-detail").disabled = !state.currentRunId && state.index.length === 0;
  }

  // ── Overview: Plotly scatter (time × duration, coloured pass/fail) ───────────
  function renderOverview() {
    const pp = plotlyPalette();
    $("lg-pass").style.background = pp.markerPass;
    $("lg-fail").style.background = pp.markerFail;

    const build = (entries, colour) => {
      const sz = (e) => 8 + 2.4 * Math.sqrt(e.configured_threads || e.observed_threads || 1);
      return {
        x: entries.map((e) => e.run_started_at),
        y: entries.map((e) => e.wall_secs),
        customdata: entries.map((e) => e.invocation_id),
        text: entries.map(
          (e) =>
            `${e.command || "?"} · ${(e.configured_threads ?? e.observed_threads)}t<br>` +
            `${e.n_nodes} nodes · ${e.wall_secs.toFixed(1)}s wall · ${e.speedup ? e.speedup.toFixed(2) + "×" : "—"}<br>` +
            `${e.run_started_at}`
        ),
        mode: "markers",
        // SVG scatter (not scattergl): at this scale perf is fine, and SVG point nodes
        // are addressable for the Playwright e2e suite (WebGL points are not).
        type: "scatter",
        marker: { color: colour, size: entries.map(sz), line: { color: pp.markerLine, width: 1 }, opacity: 0.9 },
        hovertemplate: "%{text}<extra></extra>",
        name: colour === pp.markerPass ? "passed" : "has failures",
      };
    };
    const passed = state.index.filter((e) => !e.has_failures);
    const failed = state.index.filter((e) => e.has_failures);

    const layout = {
      paper_bgcolor: pp.paper,
      plot_bgcolor: pp.plot,
      font: { color: pp.font, family: "ui-monospace, monospace", size: 11 },
      margin: { l: 64, r: 24, t: 16, b: 48 },
      showlegend: false,
      hoverlabel: { bgcolor: pp.hoverBg, bordercolor: pp.hoverBorder, font: { color: pp.font, family: "ui-monospace, monospace" } },
      xaxis: { title: { text: "run start (UTC)" }, type: "date", gridcolor: pp.grid, linecolor: pp.axisLine, zeroline: false },
      yaxis: { title: { text: "duration — wall seconds" }, gridcolor: pp.grid, linecolor: pp.axisLine, zeroline: false, rangemode: "tozero" },
    };
    const config = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] };

    const div = $("scatter");
    window.Plotly.react(div, [build(passed, pp.markerPass), build(failed, pp.markerFail)], layout, config);
    if (!div._obsClickBound) {
      div.on("plotly_click", (ev) => {
        const id = ev.points && ev.points[0] && ev.points[0].customdata;
        if (id) navigate(id);
      });
      div._obsClickBound = true;
    }

    const m = state.bundleMeta || {};
    const nFail = failed.length;
    $("overview-stats").textContent = [
      `runs    ${state.index.length}`,
      `window  ${m.days != null ? m.days + "d" : "—"}`,
      `passed  ${state.index.length - nFail}`,
      `failed  ${nFail}`,
    ].join("\n");
    $("status").textContent = `${state.index.length} runs`;
  }

  // ── Detail: SVG Gantt ───────────────────────────────────────────────────────
  function render() {
    const d = state.data;
    if (!d) return;
    const p = palette();
    const { threads, nodes } = d;
    const wallSecs = d.metadata.wall_secs;
    const pps = state.pxPerSec;
    const laneIndex = new Map(threads.map((t, i) => [t, i]));
    const innerW = Math.max(wallSecs * pps, 120);
    const width = MARGIN.left + innerW + MARGIN.right;
    const height = MARGIN.top + threads.length * LANE_H + MARGIN.bottom;
    const xAt = (off) => MARGIN.left + off * pps;
    const laneY = (t) => MARGIN.top + laneIndex.get(t) * LANE_H;

    const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}` });
    threads.forEach((t, i) => {
      svg.appendChild(svgEl("rect", { x: MARGIN.left, y: MARGIN.top + i * LANE_H, width: innerW, height: LANE_H,
        fill: i % 2 ? p.laneBandB : p.laneBandA }));
      const label = svgEl("text", { x: MARGIN.left - 10, y: MARGIN.top + i * LANE_H + LANE_H / 2 + 4,
        "text-anchor": "end", fill: p.axisText, "font-size": "12", "font-family": "ui-monospace, monospace" });
      label.textContent = t;
      svg.appendChild(label);
    });
    const step = niceStep(pps);
    const wallStartMs = new Date(d.metadata.wall_start).getTime();
    for (let s = 0; s <= wallSecs + 0.001; s += step) {
      const x = xAt(s);
      svg.appendChild(svgEl("line", { x1: x, y1: MARGIN.top, x2: x, y2: height - MARGIN.bottom, stroke: p.grid, "stroke-width": 1 }));
      const lbl = svgEl("text", { x, y: MARGIN.top - 16, "text-anchor": "middle", fill: p.axisText, "font-size": "10", "font-family": "ui-monospace, monospace" });
      lbl.textContent = fmtClock(new Date(wallStartMs + s * 1000).toISOString());
      svg.appendChild(lbl);
      const off = svgEl("text", { x, y: MARGIN.top - 4, "text-anchor": "middle", fill: p.axisText, "font-size": "9", "font-family": "ui-monospace, monospace" });
      off.textContent = "+" + s + "s";
      svg.appendChild(off);
    }
    const barPad = (LANE_H - BAR_H) / 2;
    nodes.forEach((n) => {
      const x = xAt(n.start_offset_secs);
      const w = Math.max(n.duration_secs * pps, 2);
      const y = laneY(n.thread_id) + barPad;
      const g = svgEl("g", {});
      const rect = svgEl("rect", { class: "bar", x, y, width: w, height: BAR_H, rx: 3, fill: barFill(n),
        stroke: isOk(n.status) ? p.barStroke : "#ef4444", "stroke-width": isOk(n.status) ? 0.5 : 2, style: "cursor:pointer" });
      rect.addEventListener("mousemove", (e) => showTip(e, n));
      rect.addEventListener("mouseleave", hideTip);
      g.appendChild(rect);
      if (state.showLabels && w > 28) {
        const t = svgEl("text", { x: x + 4, y: y + BAR_H / 2 + 4, fill: p.axisText, "font-size": "10",
          "font-family": "ui-monospace, monospace", "pointer-events": "none" });
        t.textContent = n.name;
        g.appendChild(t);
      }
      svg.appendChild(g);
    });
    $("chart").replaceChildren(svg);
  }

  // Tooltip
  const tip = $("tooltip");
  function showTip(evt, n) {
    tip.textContent =
      `${n.node_id}\nthread    ${n.thread_id}\nstatus    ${n.status}\n` +
      `start     ${fmtClock(n.start)} UTC  (+${n.start_offset_secs.toFixed(2)}s)\nduration  ${fmtDur(n.duration_secs)}`;
    tip.style.display = "block";
    moveTip(evt);
  }
  function moveTip(evt) {
    const pad = 14, r = tip.getBoundingClientRect();
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + r.width > window.innerWidth) x = evt.clientX - r.width - pad;
    if (y + r.height > window.innerHeight) y = evt.clientY - r.height - pad;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  const hideTip = () => (tip.style.display = "none");

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
    const eff = m.speedup && m.n_threads ? (m.speedup / m.n_threads) * 100 : 0;
    $("metadata-body").textContent = [
      `invocation ${m.invocation_id.slice(0, 8)}`,
      `nodes      ${m.n_nodes}`,
      `threads    ${m.n_threads}`,
      `wall       ${m.wall_secs.toFixed(1)}s`,
      `cpu        ${m.cpu_secs.toFixed(1)}s`,
      `speed-up   ${m.speedup ? m.speedup.toFixed(2) : "—"}×`,
      `efficiency ${eff.toFixed(0)}%`,
    ].join("\n");
    const longest = [...state.data.nodes].sort((a, b) => b.duration_secs - a.duration_secs).slice(0, 6);
    $("detail-body").textContent = longest.map((n) => `${n.duration_secs.toFixed(2).padStart(7)}s  ${n.name}`).join("\n");
  }

  function renderRunMeta() {
    const e = state.index.find((r) => r.invocation_id === state.currentRunId);
    if (!e) { $("run-meta").textContent = ""; return; }
    const cfg = e.configured_threads != null ? `${e.configured_threads}t configured` : `${e.observed_threads}t observed`;
    $("run-meta").textContent =
      `${e.command || "?"} · ${cfg}\n${e.git_sha ? e.git_sha.slice(0, 7) + " · " : ""}${e.has_failures ? "has failures" : "all passed"}`;
  }

  // ── Run picker ──────────────────────────────────────────────────────────────
  function runLabel(e) {
    const t = new Date(e.run_started_at).toLocaleTimeString("en-GB", { hour12: false, timeZone: "UTC" });
    const cfg = e.configured_threads != null ? e.configured_threads : e.observed_threads;
    const sp = e.speedup ? `${e.speedup.toFixed(2)}×` : "—";
    return `${t} · ${e.command || "?"} · ${cfg}t · ${e.n_nodes}n · ${sp}${e.has_failures ? " ⚠" : ""}`;
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
    render();
  }

  // ── Sidebar collapse ────────────────────────────────────────────────────────
  function setCollapsed(c) {
    $("app-root").classList.toggle("sidebar-collapsed", c);
    $("btn-sidebar-toggle").textContent = c ? "⟩" : "⟨";
    try { localStorage.setItem(SIDEBAR_KEY, c ? "1" : "0"); } catch (e) { /* private mode */ }
    if (state.currentView === "overview" && window.Plotly) window.Plotly.Plots.resize($("scatter"));
  }

  // ── Boot ──────────────────────────────────────────────────────────────────
  async function boot() {
    try {
      const resp = await fetch(`design-tokens.json?v=${BUILD_ID}`, { cache: "no-store" });
      if (resp.ok) state.tokens = await resp.json();
    } catch (_e) { /* keep fallbacks */ }
    if (state.tokens.brand) {
      $("brand-name").textContent = state.tokens.brand.name || "obs";
      $("brand-tagline").textContent = state.tokens.brand.tagline || "";
    }
    $("build-banner").textContent = `build ${BUILD_ID}\n${SOURCE}`;
    applyTheme(state.currentTheme, { persist: false });

    const savedZoom = Number(localStorage.getItem(ZOOM_KEY));
    if (savedZoom) state.pxPerSec = savedZoom;
    $("zoom").value = String(state.pxPerSec);
    setCollapsed(localStorage.getItem(SIDEBAR_KEY) === "1");

    // Controls
    $("btn-theme").addEventListener("click", toggleTheme);
    $("btn-sidebar-toggle").addEventListener("click", () =>
      setCollapsed(!$("app-root").classList.contains("sidebar-collapsed"))
    );
    $("nav-overview").addEventListener("click", () => navigate(null));
    $("nav-detail").addEventListener("click", () =>
      navigate(state.currentRunId || (state.index[0] && state.index[0].invocation_id))
    );
    document.querySelectorAll("#colour-seg button").forEach((b) =>
      b.addEventListener("click", () => {
        state.colourBy = b.dataset.mode;
        document.querySelectorAll("#colour-seg button").forEach((x) => x.classList.toggle("is-active", x === b));
        renderLegend();
        render();
      })
    );
    document.querySelector('#colour-seg button[data-mode="resource"]').classList.add("is-active");
    const setZoom = (v) => {
      state.pxPerSec = Math.max(2, Math.min(60, v));
      $("zoom").value = String(state.pxPerSec);
      try { localStorage.setItem(ZOOM_KEY, String(state.pxPerSec)); } catch (e) { /* private mode */ }
      render();
    };
    $("zoom").addEventListener("input", (e) => setZoom(Number(e.target.value)));
    $("btn-zoom-in").addEventListener("click", () => setZoom(state.pxPerSec + 4));
    $("btn-zoom-out").addEventListener("click", () => setZoom(state.pxPerSec - 4));
    $("chk-labels").addEventListener("change", (e) => { state.showLabels = e.target.checked; render(); });
    window.addEventListener("popstate", () => applyRoute(new URLSearchParams(location.search).get(URL_PARAM_RUN)));

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
    // Route from the URL (deep link to ?run=… opens detail; otherwise overview).
    await applyRoute(new URLSearchParams(location.search).get(URL_PARAM_RUN));
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
