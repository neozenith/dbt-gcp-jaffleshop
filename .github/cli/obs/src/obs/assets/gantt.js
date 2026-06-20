/* obs Gantt viewer — vanilla JS, no build step.
 *
 * Loads:
 *   design-tokens.json  → theme provider (light/dark/system) + resource/status colours
 *   index.json          → run picker (every run in the extracted window)
 *   runs/<id>.json      → the selected run's per-node Gantt payload (lazy, cached)
 *
 * Renders an SVG Gantt: one lane per dbt worker thread, one bar per node's execution
 * interval — so parallelism and bottlenecks are visible, and the run picker lets you
 * compare thread-count permutations across the window.
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
  const LS = { theme: "obs.theme", collapsed: "obs.collapsed", zoom: "obs.zoom" };

  // Built-in fallbacks used only if design-tokens.json fails to load.
  const FALLBACK_TOKENS = {
    brand: { name: "obs · Gantt", tagline: "dbt run telemetry" },
    defaultTheme: "system",
    resourceColours: { model: "#0072B2", test: "#E69F00", _fallback: "#94A3B8" },
    statusColours: { success: "#10B981", error: "#EF4444", _fallback: "#94A3B8" },
    themes: {
      dark: { bg: "#0f172a", surface: "#020617", surfaceAlt: "#1e293b", text: "#f1f5f9",
        textMuted: "#94a3b8", textFaint: "#64748b", border: "#334155", accent: "#38bdf8",
        grid: "#1e293b", laneBandA: "#0f172a", laneBandB: "#0b1220", barStroke: "rgba(0,0,0,0.35)" },
      light: { bg: "#ffffff", surface: "#f8fafc", surfaceAlt: "#e2e8f0", text: "#0f172a",
        textMuted: "#475569", textFaint: "#94a3b8", border: "#cbd5e1", accent: "#0284c7",
        grid: "#e2e8f0", laneBandA: "#ffffff", laneBandB: "#f1f5f9", barStroke: "rgba(15,23,42,0.18)" },
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
    pxPerSec: 14,
    colourBy: "resource",
    showLabels: false,
    theme: "system",
    resolvedTheme: "dark",
    collapsed: false,
  };

  const $ = (id) => document.getElementById(id);
  const svgEl = (tag, attrs) => {
    const e = document.createElementNS(SVG_NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  };
  const stripMeta = (obj) => Object.fromEntries(Object.entries(obj || {}).filter(([k]) => !k.startsWith("_")));

  // ── Theme provider ─────────────────────────────────────────────────────────
  const palette = () => state.tokens.themes[state.resolvedTheme] || FALLBACK_TOKENS.themes.dark;

  function applyTheme() {
    const sys = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    state.resolvedTheme = state.theme === "system" ? sys : state.theme;
    const p = palette();
    const root = document.documentElement;
    root.dataset.theme = state.resolvedTheme;
    const map = {
      "--obs-bg": p.bg, "--obs-surface": p.surface, "--obs-surface-alt": p.surfaceAlt,
      "--obs-text": p.text, "--obs-text-muted": p.textMuted, "--obs-text-faint": p.textFaint,
      "--obs-border": p.border, "--obs-accent": p.accent, "--obs-grid": p.grid,
      "--obs-lane-a": p.laneBandA, "--obs-lane-b": p.laneBandB, "--obs-bar-stroke": p.barStroke,
    };
    for (const k in map) if (map[k]) root.style.setProperty(k, map[k]);
    if (state.tokens.fonts) {
      if (state.tokens.fonts.mono) root.style.setProperty("--obs-font-mono", state.tokens.fonts.mono);
      if (state.tokens.fonts.sans) root.style.setProperty("--obs-font-sans", state.tokens.fonts.sans);
    }
    document.querySelectorAll("#theme-seg button").forEach((b) =>
      b.classList.toggle("active", b.dataset.theme === state.theme)
    );
    if (state.data) render();
    renderLegend();
  }

  function setTheme(t) {
    state.theme = t;
    localStorage.setItem(LS.theme, t);
    applyTheme();
  }

  // ── Colour helpers ─────────────────────────────────────────────────────────
  const resourceColour = (rt) =>
    (state.tokens.resourceColours || {})[rt] || (state.tokens.resourceColours || {})._fallback || "#94A3B8";
  const statusColour = (s) =>
    (state.tokens.statusColours || {})[(s || "").toLowerCase()] ||
    (state.tokens.statusColours || {})._fallback || "#94A3B8";
  const isOk = (s) => ["success", "pass"].includes((s || "").toLowerCase());
  const barFill = (n) => (state.colourBy === "status" ? statusColour(n.status) : resourceColour(n.resource_type));

  const fmtClock = (iso) => new Date(iso).toLocaleTimeString("en-GB", { hour12: false, timeZone: "UTC" });
  const fmtDur = (s) => (s >= 1 ? s.toFixed(2) + "s" : (s * 1000).toFixed(0) + "ms");
  const dayOf = (iso) => new Date(iso).toISOString().slice(0, 10);

  function niceStep(pxPerSec) {
    for (const step of TICK_STEPS) if (step * pxPerSec >= 72) return step;
    return TICK_STEPS[TICK_STEPS.length - 1];
  }

  // ── Tooltip ──────────────────────────────────────────────────────────────
  const tip = $("tooltip");
  function showTip(evt, n) {
    tip.textContent =
      `${n.node_id}\n` +
      `thread    ${n.thread_id}\n` +
      `status    ${n.status}\n` +
      `start     ${fmtClock(n.start)} UTC  (+${n.start_offset_secs.toFixed(2)}s)\n` +
      `duration  ${fmtDur(n.duration_secs)}`;
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

  // ── Chart render ───────────────────────────────────────────────────────────
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
    const xAt = (offset) => MARGIN.left + offset * pps;
    const laneY = (t) => MARGIN.top + laneIndex.get(t) * LANE_H;

    const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}` });

    threads.forEach((t, i) => {
      svg.appendChild(svgEl("rect", {
        x: MARGIN.left, y: MARGIN.top + i * LANE_H, width: innerW, height: LANE_H,
        fill: i % 2 ? p.laneBandB : p.laneBandA,
      }));
      const label = svgEl("text", {
        x: MARGIN.left - 10, y: MARGIN.top + i * LANE_H + LANE_H / 2 + 4,
        "text-anchor": "end", fill: p.textMuted, "font-size": "12",
      });
      label.textContent = t;
      svg.appendChild(label);
    });

    const step = niceStep(pps);
    const wallStartMs = new Date(d.metadata.wall_start).getTime();
    for (let s = 0; s <= wallSecs + 0.001; s += step) {
      const x = xAt(s);
      svg.appendChild(svgEl("line", {
        x1: x, y1: MARGIN.top, x2: x, y2: height - MARGIN.bottom, stroke: p.grid, "stroke-width": 1,
      }));
      const lbl = svgEl("text", { x, y: MARGIN.top - 16, "text-anchor": "middle", fill: p.textFaint, "font-size": "10" });
      lbl.textContent = fmtClock(new Date(wallStartMs + s * 1000).toISOString());
      svg.appendChild(lbl);
      const off = svgEl("text", { x, y: MARGIN.top - 4, "text-anchor": "middle", fill: p.textFaint, "font-size": "9" });
      off.textContent = "+" + s + "s";
      svg.appendChild(off);
    }

    const barPad = (LANE_H - BAR_H) / 2;
    nodes.forEach((n) => {
      const x = xAt(n.start_offset_secs);
      const w = Math.max(n.duration_secs * pps, 2);
      const y = laneY(n.thread_id) + barPad;
      const g = svgEl("g", {});
      const rect = svgEl("rect", {
        class: "bar", x, y, width: w, height: BAR_H, rx: 3, fill: barFill(n),
        stroke: isOk(n.status) ? p.barStroke : "#ef4444", "stroke-width": isOk(n.status) ? 0.5 : 2,
      });
      rect.addEventListener("mousemove", (e) => showTip(e, n));
      rect.addEventListener("mouseleave", hideTip);
      g.appendChild(rect);
      if (state.showLabels && w > 28) {
        const t = svgEl("text", {
          x: x + 4, y: y + BAR_H / 2 + 4, fill: p.text, "font-size": "10", "pointer-events": "none",
        });
        t.textContent = n.name;
        g.appendChild(t);
      }
      svg.appendChild(g);
    });

    $("chart").replaceChildren(svg);
  }

  // ── Sidebar panels ─────────────────────────────────────────────────────────
  function renderLegend() {
    const body = $("legend-body");
    const entries =
      state.colourBy === "status"
        ? Object.entries(stripMeta(state.tokens.statusColours))
        : Object.entries(stripMeta(state.tokens.resourceColours));
    const present = state.data
      ? new Set(state.data.nodes.map((n) => (state.colourBy === "status" ? n.status.toLowerCase() : n.resource_type)))
      : null;
    body.replaceChildren();
    entries
      .filter(([k]) => !present || present.has(k))
      .forEach(([label, colour]) => {
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
    $("detail-body").textContent = longest
      .map((n) => `${n.duration_secs.toFixed(2).padStart(7)}s  ${n.name}`)
      .join("\n");
  }

  function renderRunMeta() {
    const e = state.index.find((r) => r.invocation_id === state.currentRunId);
    if (!e) { $("run-meta").textContent = ""; return; }
    const cfg = e.configured_threads != null ? `${e.configured_threads}t configured` : `${e.observed_threads}t observed`;
    $("run-meta").textContent =
      `${e.command || "?"} · ${cfg}\n` +
      `${e.git_sha ? e.git_sha.slice(0, 7) + " · " : ""}${e.has_failures ? "has failures" : "all passed"}`;
  }

  // ── Run picker ─────────────────────────────────────────────────────────────
  function runLabel(e) {
    const t = new Date(e.run_started_at).toLocaleTimeString("en-GB", { hour12: false, timeZone: "UTC" });
    const cfg = e.configured_threads != null ? e.configured_threads : e.observed_threads;
    const sp = e.speedup ? `${e.speedup.toFixed(2)}×` : "—";
    const flag = e.has_failures ? " ⚠" : "";
    return `${t} · ${e.command || "?"} · ${cfg}t · ${e.n_nodes}n · ${sp}${flag}`;
  }

  function populatePicker() {
    const picker = $("run-picker");
    picker.replaceChildren();
    const byDay = new Map();
    for (const e of state.index) {
      const day = dayOf(e.run_started_at);
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
    picker.addEventListener("change", () => selectRun(picker.value));
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

  // ── Sidebar collapse ───────────────────────────────────────────────────────
  function setCollapsed(c) {
    state.collapsed = c;
    $("app").classList.toggle("collapsed", c);
    localStorage.setItem(LS.collapsed, c ? "1" : "0");
  }

  // ── Boot ──────────────────────────────────────────────────────────────────
  async function boot() {
    // 1. Design tokens (theme + colours). Soft-fail to built-ins.
    try {
      const resp = await fetch(`design-tokens.json?v=${BUILD_ID}`, { cache: "no-store" });
      if (resp.ok) state.tokens = await resp.json();
    } catch (_e) { /* keep fallbacks */ }
    if (state.tokens.brand) {
      $("brand-name").textContent = (state.tokens.brand.name || "obs") + " · Gantt";
      $("brand-tagline").textContent = state.tokens.brand.tagline || "";
    }
    $("build-banner").textContent = `build ${BUILD_ID}\n${SOURCE}`;

    // 2. Restore persisted prefs.
    state.theme = localStorage.getItem(LS.theme) || state.tokens.defaultTheme || "system";
    const savedZoom = Number(localStorage.getItem(LS.zoom));
    if (savedZoom) state.pxPerSec = savedZoom;
    $("zoom").value = String(state.pxPerSec);
    setCollapsed(localStorage.getItem(LS.collapsed) === "1");
    applyTheme();
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (state.theme === "system") applyTheme();
    });

    // 3. Wire controls.
    document.querySelectorAll("#theme-seg button").forEach((b) =>
      b.addEventListener("click", () => setTheme(b.dataset.theme))
    );
    $("btn-collapse").addEventListener("click", () => setCollapsed(true));
    $("rail-expand").addEventListener("click", () => setCollapsed(false));
    document.querySelectorAll("#colour-seg button").forEach((b) =>
      b.addEventListener("click", () => {
        state.colourBy = b.dataset.mode;
        document.querySelectorAll("#colour-seg button").forEach((x) => x.classList.toggle("active", x === b));
        renderLegend();
        render();
      })
    );
    document.querySelector('#colour-seg button[data-mode="resource"]').classList.add("active");
    const setZoom = (v) => {
      state.pxPerSec = Math.max(2, Math.min(60, v));
      $("zoom").value = String(state.pxPerSec);
      localStorage.setItem(LS.zoom, String(state.pxPerSec));
      render();
    };
    $("zoom").addEventListener("input", (e) => setZoom(Number(e.target.value)));
    $("btn-zoom-in").addEventListener("click", () => setZoom(state.pxPerSec + 4));
    $("btn-zoom-out").addEventListener("click", () => setZoom(state.pxPerSec - 4));
    $("chk-labels").addEventListener("change", (e) => { state.showLabels = e.target.checked; render(); });

    // 4. Load the run index + select the newest run.
    try {
      const resp = await fetch(`index.json?v=${BUILD_ID}`, { cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status} fetching index.json`);
      const doc = await resp.json();
      state.index = doc.index || [];
    } catch (err) {
      $("status").textContent = "error: " + err.message;
      return;
    }
    if (state.index.length === 0) { $("status").textContent = "no runs in window"; return; }
    populatePicker();
    await selectRun(state.index[0].invocation_id);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
