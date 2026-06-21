"""The Gantt engine — turns Elementary telemetry into a multi-run JSON bundle and writes
it next to a templated HTML+JS viewer.

This is the *transform* half (the I/O half is ``elementary.py``). Both builders are pure
(``list[dict]`` in, JSON-able ``dict`` out — so they unit-test without a warehouse):

* :func:`build_gantt_payload` — one invocation's rows → that run's Gantt payload.
* :func:`build_bundle` — a window of invocations + run-result rows → ``{index, runs}``.

:func:`write_bundle` then writes the "index + per-item" layout (``index.json`` +
``runs/<id>.json``), copies ``design-tokens.json`` (the brand/theme curate point), and
drops the templated ``gantt.html`` / ``gantt.js`` — substituting ``{{BUILD_ID}}`` and
``{{SOURCE}}``, exactly as ``adaf``'s sdag viewer does.

Per-run payload schema (one ``runs/<id>.json``, consumed by ``assets/gantt.js``)::

    {
      "metadata": { invocation_id, build_id, source, generated_at,
                    n_nodes, n_threads, wall_start, wall_end,
                    wall_secs, cpu_secs, speedup, resource_types[] },
      "threads": ["Thread-1 (worker)", ...],          # lane order, top-to-bottom
      "nodes":   [ { thread_id, node_id, name, resource_type, status,
                     start, end,                       # ISO-8601
                     start_offset_secs, duration_secs  # numbers, for x-positioning
                   }, ... ]
    }
"""

# Standard Library
import datetime as dt
import json
import logging
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Templates ship inside the package (resolved relative to THIS file, not cwd).
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

INDEX_JSON = "index.json"
RUNS_DIR = "runs"
OBS_HTML = "obs.html"
OBS_JS = "obs.js"
DESIGN_TOKENS = "design-tokens.json"

# resource_type → colour. Kept in sync with gantt.js's RESOURCE_COLOURS (Okabe-Ito,
# colour-blind-safe). The payload carries resource_type; the JS owns the actual palette,
# but this is the authoritative reference both sides agree on.
RESOURCE_COLOURS: dict[str, str] = {
    "model": "#0072B2",
    "test": "#E69F00",
    "unit_test": "#CC79A7",
    "seed": "#009E73",
    "snapshot": "#D55E00",
    "source": "#56B4E9",
    "exposure": "#F0E442",
    "operation": "#999999",
}

_THREAD_NUM = re.compile(r"(\d+)")


def _parse_ts(value: str) -> dt.datetime:
    """Parse an Elementary ISO-8601 timestamp (``2026-06-17T05:59:04.754117Z``).

    ``datetime.fromisoformat`` handles the trailing ``Z`` on Python ≥3.11; we still
    normalise it for safety. Result is timezone-aware (UTC).
    """
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _thread_sort_key(thread_id: str) -> tuple[int, str]:
    """Order lanes naturally: ``Thread-2`` before ``Thread-10``, unknowns last."""
    m = _THREAD_NUM.search(thread_id or "")
    return (int(m.group(1)) if m else 1_000_000, thread_id or "")


def _iso(value: dt.datetime) -> str:
    """UTC ISO-8601 with a ``Z`` suffix (what the JS ``Date`` parser expects)."""
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _to_canonical_iso(value: Any) -> str | None:
    """Best-effort parse of an Elementary timestamp string → canonical UTC ISO, else None."""
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return _iso(value)
    try:
        return _iso(_parse_ts(str(value)))
    except ValueError:
        return None


def _is_ok(status: str | None) -> bool:
    """Whether a node status counts as a clean pass (vs error/fail/skip)."""
    return (status or "").lower() in ("success", "pass")


def build_gantt_payload(rows: list[dict[str, Any]], invocation_id: str, *, source_label: str) -> dict[str, Any]:
    """Pure transform: run-result rows → the Gantt JSON payload.

    Computes per-node start offsets from the run's wall-clock start, sorts thread
    lanes naturally, and derives the headline stats (wall vs CPU time ⇒ parallel
    speed-up) the viewer banners.
    """
    if not rows:
        raise ValueError("build_gantt_payload: no rows")

    parsed: list[dict[str, Any]] = []
    for r in rows:
        start = _parse_ts(r["execute_started_at"])
        end = _parse_ts(r["execute_completed_at"]) if r.get("execute_completed_at") else start
        parsed.append({**r, "_start": start, "_end": end})

    wall_start = min(p["_start"] for p in parsed)
    wall_end = max(p["_end"] for p in parsed)
    wall_secs = (wall_end - wall_start).total_seconds()
    cpu_secs = sum(float(p.get("duration_secs") or 0.0) for p in parsed)

    threads = sorted({p["thread_id"] for p in parsed}, key=_thread_sort_key)
    resource_types = sorted({(p.get("resource_type") or "unknown") for p in parsed})

    nodes: list[dict[str, Any]] = []
    for p in sorted(parsed, key=lambda x: (_thread_sort_key(x["thread_id"]), x["_start"])):
        nodes.append(
            {
                "thread_id": p["thread_id"],
                "node_id": p["node_id"],
                "name": p.get("name") or p["node_id"].rsplit(".", 1)[-1],
                "resource_type": p.get("resource_type") or "unknown",
                "status": p.get("status") or "unknown",
                "start": _iso(p["_start"]),
                "end": _iso(p["_end"]),
                "start_offset_secs": round((p["_start"] - wall_start).total_seconds(), 3),
                "duration_secs": round(float(p.get("duration_secs") or 0.0), 3),
            }
        )

    return {
        "metadata": {
            "invocation_id": invocation_id,
            "source": source_label,
            "n_nodes": len(nodes),
            "n_threads": len(threads),
            "wall_start": _iso(wall_start),
            "wall_end": _iso(wall_end),
            "wall_secs": round(wall_secs, 3),
            "cpu_secs": round(cpu_secs, 3),
            # CPU/wall ⇒ effective parallelism; compare to n_threads for thread efficiency.
            "speedup": round(cpu_secs / wall_secs, 3) if wall_secs > 0 else None,
            "resource_types": resource_types,
        },
        "threads": threads,
        "nodes": nodes,
    }


# ─── Output (JSON + templated HTML/JS) ───────────────────────────────────────


def _build_id() -> str:
    """Monotonic, human-readable build id stamped into HTML + JSON for cache-busting."""
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def _apply_tokens(template_text: str, *, build_id: str, source_label: str) -> str:
    """Substitute the two viewer tokens. Centralised so HTML and JS share one path."""
    return template_text.replace("{{BUILD_ID}}", build_id).replace("{{SOURCE}}", source_label)


def _run_summary(payload: dict[str, Any], inv: dict[str, Any]) -> dict[str, Any]:
    """One lightweight index row for the run picker: per-run Gantt stats + the
    ``dbt_invocations`` metadata (command, configured threads, git sha) that lets you
    compare thread permutations."""
    m = payload["metadata"]
    return {
        "invocation_id": m["invocation_id"],
        "command": inv.get("command"),
        "configured_threads": inv.get("threads"),  # the real --threads value, if recorded
        "observed_threads": m["n_threads"],  # distinct thread_id lanes that actually ran
        "run_started_at": _to_canonical_iso(inv.get("run_started_at")) or m["wall_start"],
        "git_sha": inv.get("git_sha"),
        "target_name": inv.get("target_name"),
        "dbt_version": inv.get("dbt_version"),
        "full_refresh": inv.get("full_refresh"),
        "n_nodes": m["n_nodes"],
        "wall_secs": m["wall_secs"],
        "cpu_secs": m["cpu_secs"],
        "speedup": m["speedup"],
        "has_failures": any(not _is_ok(n["status"]) for n in payload["nodes"]),
    }


def build_bundle(
    invocations: list[dict[str, Any]],
    result_rows: list[dict[str, Any]],
    *,
    source_label: str,
    days: int,
) -> dict[str, Any]:
    """Pure transform: window rows → a multi-run bundle (index + per-run payloads).

    Groups ``result_rows`` by ``invocation_id``, builds a pure per-run Gantt payload for
    each (reusing :func:`build_gantt_payload`), and joins the ``dbt_invocations`` metadata
    into a lightweight, newest-first ``index`` for the run picker.
    """
    by_inv: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in result_rows:
        by_inv[r["invocation_id"]].append(r)
    inv_by_id = {i["invocation_id"]: i for i in invocations}

    index: list[dict[str, Any]] = []
    runs: dict[str, dict[str, Any]] = {}
    for inv_id, rows in by_inv.items():
        payload = build_gantt_payload(rows, inv_id, source_label=source_label)
        runs[inv_id] = payload
        index.append(_run_summary(payload, inv_by_id.get(inv_id, {})))

    index.sort(key=lambda e: e["run_started_at"], reverse=True)
    return {
        "metadata": {
            "source": source_label,
            "days": days,
            "n_runs": len(runs),
            "generated_at": _iso(dt.datetime.now(dt.UTC)),
        },
        "index": index,
        "runs": runs,
    }


def write_bundle(output_dir: Path, bundle: dict[str, Any], *, assets_dir: Path = ASSETS_DIR) -> str:
    """Write the viewer bundle into ``output_dir`` and return the build id.

    Layout (the "index + per-item" manifest shape — the viewer lazy-loads each run):
        index.json                 # run-picker summaries + bundle metadata
        runs/<invocation_id>.json  # one per-run Gantt payload
        design-tokens.json         # brand/theme tokens (copied from assets; curate point)
        obs.html / obs.js          # templated SPA viewer (overview scatter + run-detail Gantt)
    """
    html_tpl = assets_dir / OBS_HTML
    js_tpl = assets_dir / OBS_JS
    tokens_src = assets_dir / DESIGN_TOKENS
    for asset in (html_tpl, js_tpl, tokens_src):
        if not asset.exists():
            raise FileNotFoundError(f"viewer asset missing at {asset}")
    output_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = output_dir / RUNS_DIR
    runs_dir.mkdir(parents=True, exist_ok=True)

    build_id = _build_id()
    source_label = str(bundle.get("metadata", {}).get("source", ""))
    bundle["metadata"]["build_id"] = build_id

    # Per-run payloads (lazy-loaded by the viewer on selection).
    for inv_id, payload in bundle["runs"].items():
        payload["metadata"]["build_id"] = build_id
        (runs_dir / f"{inv_id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Lightweight index (run picker) — carries metadata + the summaries, NOT the run payloads.
    index_doc = {"metadata": bundle["metadata"], "index": bundle["index"]}
    (output_dir / INDEX_JSON).write_text(json.dumps(index_doc, indent=2), encoding="utf-8")

    # Brand/theme tokens: copied verbatim so editing the source curates the viewer.
    shutil.copyfile(tokens_src, output_dir / DESIGN_TOKENS)

    (output_dir / OBS_HTML).write_text(
        _apply_tokens(html_tpl.read_text(encoding="utf-8"), build_id=build_id, source_label=source_label),
        encoding="utf-8",
    )
    (output_dir / OBS_JS).write_text(
        _apply_tokens(js_tpl.read_text(encoding="utf-8"), build_id=build_id, source_label=source_label),
        encoding="utf-8",
    )
    log.info(
        "wrote %s + %d run file(s) + %s + %s into %s (build_id=%s)",
        INDEX_JSON,
        len(bundle["runs"]),
        DESIGN_TOKENS,
        OBS_HTML,
        output_dir,
        build_id,
    )
    return build_id
