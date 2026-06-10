"""The sdag viewer engine — builds the Cytoscape.js assets and serves them.

This is the *visualisation* half of the data-product tooling (the analysis half is graph.py +
commands/dataproducts.py). Given the full dbt manifest and the resolved named selectors, it emits two
Cytoscape-compatible JSON files next to a templated HTML+JS viewer:

* ``full_graph.json``  — every entity (model/test/seed/snapshot/source/...) and every lineage edge,
                         each entity placed inside a compound parent for its primary matching selector
                         (all memberships recorded on ``data.selectors``).
* ``super_graph.json`` — one super-node per selector, internal edges collapsed, inter-selector edges
                         aggregated and weighted with ``count``.

Ported from the standalone ``sdag.py`` script, with two adaptations for this package:

* **No networkx.** sdag used ``nx.DiGraph`` purely as a node/edge container; here the builders take a
  plain ``nodes`` dict + ``edges`` list (see ``load_full_manifest``), so no dependency is added.
* **The full manifest, not the data-node graph.** Unlike ``graph.Graph`` (which filters to data nodes
  for boundary classification), the viewer shows *everything* — tests and semantic models included — so
  it reads its own un-filtered view of the manifest.

The HTML/JS templates live in ``adaf/assets/`` and carry two tokens substituted at write time:
``{{BUILD_ID}}`` (cache-bust + banner) and ``{{SOURCE}}`` (the manifest the graph was read from).
"""

# Standard Library
import datetime as dt
import http.server
import json
import logging
import math
import socketserver
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Template assets ship inside the package (resolved relative to THIS file, not cwd — the package is
# imported via cwd-on-path but its assets are package-relative).
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

FULL_GRAPH_JSON = "full_graph.json"
SUPER_GRAPH_JSON = "super_graph.json"
SDAG_HTML = "sdag.html"
SDAG_JS = "sdag.js"

UNMATCHED_ID = "__unmatched__"

# Pastel-tinted palette per resource_type — kept in sync with sdag.js's RESOURCE_COLOURS so the JSON's
# `colour` hint and the stylesheet agree.
NODE_COLOURS: dict[str, str] = {
    "model": "#3b82f6",
    "test": "#a855f7",
    "seed": "#10b981",
    "snapshot": "#f59e0b",
    "source": "#6b7280",
    "analysis": "#ec4899",
    "exposure": "#ef4444",
    "metric": "#14b8a6",
}


# ─── Full-manifest load (everything, not just data nodes) ────────────────────


def load_full_manifest(path: Path | str) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]]]:
    """Read manifest.json into ``(nodes, edges)`` over EVERY resource type (for the viewer).

    ``nodes`` maps unique_id → display attrs; ``edges`` is the ``parent_map`` flattened to
    ``(parent, child)`` and filtered to edges whose both endpoints are present (drops references to
    disabled/deferred/external resources).
    """
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"dbt manifest not found at '{manifest_path}'. Run `dbt parse` or pass --parse.")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    nodes: dict[str, dict[str, Any]] = {}
    for section in ("nodes", "sources"):
        for uid, node in (data.get(section) or {}).items():
            tags = node.get("tags") if isinstance(node.get("tags"), list) else []
            fqn = node.get("fqn") if isinstance(node.get("fqn"), list) else []
            nodes[uid] = {
                "unique_id": uid,
                "resource_type": node.get("resource_type") or ("source" if section == "sources" else ""),
                "name": node.get("name") or uid.rsplit(".", 1)[-1],
                "fqn": [str(p) for p in fqn],
                "tags": [str(t) for t in tags],
                "materialized": (node.get("config") or {}).get("materialized"),
                "schema": node.get("schema"),
            }

    parent_map = data.get("parent_map") or {}
    edges_all = [(p, c) for c, parents in parent_map.items() for p in (parents or [])]
    known = set(nodes)
    edges = [(p, c) for p, c in edges_all if p in known and c in known]
    log.debug(
        "viewer manifest: %d nodes, %d edges (%d cross-package refs dropped)",
        len(nodes),
        len(edges),
        len(edges_all) - len(edges),
    )
    return nodes, edges


# ─── Cytoscape JSON builders (pure) ──────────────────────────────────────────


def _primary_selector(memberships: list[str], sel_size: dict[str, int]) -> str | None:
    """Pick the smallest matching selector (most specific) as the compound parent."""
    if not memberships:
        return None
    return min(memberships, key=lambda s: (sel_size.get(s, 0), s))


def build_full_graph_json(
    nodes: dict[str, dict[str, Any]],
    edges: list[tuple[str, str]],
    resolved: dict[str, set[str]],
) -> dict[str, Any]:
    """Cytoscape JSON: every entity + every edge, grouped by compound selector nodes.

    A node matching multiple selectors is placed inside the smallest (most specific) one as its
    ``parent``; the full membership list is also stored on ``data.selectors`` so the viewer can
    highlight every containing selector when the node is tapped.
    """
    node_to_selectors: dict[str, list[str]] = defaultdict(list)
    for sel_name, members in resolved.items():
        for uid in members:
            if uid in nodes:
                node_to_selectors[uid].append(sel_name)

    sel_size = {name: len(members) for name, members in resolved.items()}
    elements: list[dict[str, Any]] = []

    # 1. One compound parent node per non-empty selector.
    for sel_name, members in resolved.items():
        present = [uid for uid in members if uid in nodes]
        if not present:
            continue
        elements.append(
            {
                "data": {
                    "id": f"sel::{sel_name}",
                    "label": sel_name,
                    "kind": "selector_compound",
                    "selector": sel_name,
                    "n_members": len(present),
                },
                "classes": "selector-compound",
            }
        )

    # 2. Catch-all compound for nodes matched by no selector.
    unmatched_uids = [uid for uid in nodes if uid not in node_to_selectors]
    if unmatched_uids:
        elements.append(
            {
                "data": {
                    "id": f"sel::{UNMATCHED_ID}",
                    "label": "NO SELECTOR",
                    "kind": "selector_compound",
                    "selector": UNMATCHED_ID,
                    "n_members": len(unmatched_uids),
                },
                "classes": "selector-compound unmatched",
            }
        )

    # 3. Leaf entity nodes.
    for uid, attrs in nodes.items():
        memberships = node_to_selectors.get(uid, [])
        primary = _primary_selector(memberships, sel_size)
        parent_id = f"sel::{primary}" if primary else f"sel::{UNMATCHED_ID}"
        rt = attrs.get("resource_type") or ""
        elements.append(
            {
                "data": {
                    "id": uid,
                    "label": attrs.get("name") or uid.rsplit(".", 1)[-1],
                    "parent": parent_id,
                    "kind": "entity",
                    "resource_type": rt,
                    "tags": attrs.get("tags") or [],
                    "materialized": attrs.get("materialized"),
                    "schema": attrs.get("schema"),
                    "fqn": attrs.get("fqn") or [],
                    "selectors": memberships,
                    "primary_selector": primary,
                    "colour": NODE_COLOURS.get(rt, "#94a3b8"),
                },
                "classes": f"entity entity-{rt}",
            }
        )

    # 4. Lineage edges.
    for parent_uid, child_uid in edges:
        elements.append(
            {
                "data": {
                    "id": f"e::{parent_uid}->{child_uid}",
                    "source": parent_uid,
                    "target": child_uid,
                    "kind": "lineage",
                },
                "classes": "edge-lineage",
            }
        )

    return {
        "elements": elements,
        "metadata": {
            "n_nodes": len(nodes),
            "n_edges": len(edges),
            "n_selectors": sum(1 for members in resolved.values() if any(uid in nodes for uid in members)),
            "n_unmatched_nodes": len(unmatched_uids),
        },
    }


def build_super_graph_json(
    nodes: dict[str, dict[str, Any]],
    edges: list[tuple[str, str]],
    resolved: dict[str, set[str]],
) -> dict[str, Any]:
    """Collapse each selector into a super-node; aggregate cross-selector edges.

    A unique_id may belong to multiple selectors — every membership contributes to that selector's
    super-node, and each manifest edge fans out across the cross-product of (source-memberships ×
    target-memberships). Identical ``(src_super, tgt_super, kind)`` triples collapse to one edge with a
    ``count``. Edges that stay inside one super (or inside the intersection of two overlapping supers)
    are dropped as internal and tallied in metadata.
    """
    uid_to_supers: dict[str, list[str]] = defaultdict(list)
    for sel_name, members in resolved.items():
        for uid in members:
            if uid in nodes:
                uid_to_supers[uid].append(sel_name)
    for uid in nodes:
        if uid not in uid_to_supers:
            uid_to_supers[uid].append(UNMATCHED_ID)

    super_members: dict[str, list[str]] = defaultdict(list)
    for uid, supers in uid_to_supers.items():
        for s in supers:
            super_members[s].append(uid)

    elements: list[dict[str, Any]] = []
    for sname, member_uids in super_members.items():
        breakdown = Counter((nodes[uid].get("resource_type") or "unknown") for uid in member_uids if uid in nodes)
        n_members = len(member_uids)
        elements.append(
            {
                "data": {
                    "id": sname,
                    "label": "NO SELECTOR" if sname == UNMATCHED_ID else sname,
                    "kind": "super",
                    "n_members": n_members,
                    # log1p sizing keeps the small end distinguishable while big nodes still dominate.
                    "log_members": round(math.log1p(n_members), 4),
                    "breakdown": dict(breakdown),
                    "is_unmatched": sname == UNMATCHED_ID,
                },
                "classes": "super" + (" unmatched" if sname == UNMATCHED_ID else ""),
            }
        )

    # Aggregate cross-super edges. An edge (parent, child) contributes to super-edge (ps, cs) iff
    # ps != cs AND the edge is not internal to BOTH ps and cs (the latter prevents phantom edges
    # between overlapping selectors). internal_edges tallies manifest edges that crossed nothing.
    edge_counts: Counter[tuple[str, str, str]] = Counter()
    internal_edges = 0
    super_uid_sets: dict[str, set[str]] = {s: set(uids) for s, uids in super_members.items()}
    for parent_uid, child_uid in edges:
        p_supers = uid_to_supers[parent_uid]
        c_supers = uid_to_supers[child_uid]
        contributed = False
        for ps in p_supers:
            for cs in c_supers:
                if ps == cs:
                    continue
                if child_uid in super_uid_sets[ps] and parent_uid in super_uid_sets[cs]:
                    continue  # edge internal to BOTH ps and cs
                edge_counts[(ps, cs, "lineage")] += 1
                contributed = True
        if not contributed:
            internal_edges += 1

    for (src, tgt, kind), count in edge_counts.items():
        elements.append(
            {
                "data": {
                    "id": f"se::{src}->{tgt}::{kind}",
                    "source": src,
                    "target": tgt,
                    "kind": kind,
                    "count": count,
                    "log_count": round(math.log1p(count), 4),
                },
                "classes": f"edge-{kind}",
            }
        )

    return {
        "elements": elements,
        "metadata": {
            "n_supers": len(super_members),
            "n_super_edges": len(edge_counts),
            "n_internal_edges_collapsed": internal_edges,
        },
    }


# ─── Output (JSON + templated HTML/JS) ───────────────────────────────────────


def _build_id() -> str:
    """Monotonic, human-readable build id stamped into HTML + JSON for cache-busting + verification."""
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def _apply_tokens(template_text: str, *, build_id: str, source_label: str) -> str:
    """Substitute the two viewer tokens. Centralised so HTML and JS go through the same path."""
    return template_text.replace("{{BUILD_ID}}", build_id).replace("{{SOURCE}}", source_label)


def write_outputs(
    output_dir: Path,
    full_graph: dict[str, Any],
    super_graph: dict[str, Any],
    *,
    source_label: str,
    assets_dir: Path = ASSETS_DIR,
) -> str:
    """Write both JSON files plus the templated HTML + JS viewer into ``output_dir``; return build id."""
    html_tpl = assets_dir / SDAG_HTML
    js_tpl = assets_dir / SDAG_JS
    for template in (html_tpl, js_tpl):
        if not template.exists():
            raise FileNotFoundError(f"viewer template missing at {template}")
    output_dir.mkdir(parents=True, exist_ok=True)

    build_id = _build_id()
    for graph in (full_graph, super_graph):
        graph["metadata"]["build_id"] = build_id
        graph["metadata"]["source"] = source_label

    (output_dir / FULL_GRAPH_JSON).write_text(json.dumps(full_graph, indent=2), encoding="utf-8")
    (output_dir / SUPER_GRAPH_JSON).write_text(json.dumps(super_graph, indent=2), encoding="utf-8")
    (output_dir / SDAG_HTML).write_text(
        _apply_tokens(html_tpl.read_text(encoding="utf-8"), build_id=build_id, source_label=source_label),
        encoding="utf-8",
    )
    (output_dir / SDAG_JS).write_text(
        _apply_tokens(js_tpl.read_text(encoding="utf-8"), build_id=build_id, source_label=source_label),
        encoding="utf-8",
    )
    log.info(
        "wrote %s, %s, %s, %s into %s (build_id=%s)",
        FULL_GRAPH_JSON,
        SUPER_GRAPH_JSON,
        SDAG_HTML,
        SDAG_JS,
        output_dir,
        build_id,
    )
    return build_id


def serve(output_dir: Path, port: int) -> None:
    """Host ``output_dir`` over HTTP with no-store headers so reloads always re-fetch fresh assets."""

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, directory=str(output_dir), **kw)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            super().end_headers()

        def log_message(self, format: str, *fargs: Any) -> None:
            log.debug("http: %s", format % fargs if fargs else format)

    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(("127.0.0.1", port), _Handler)
    except OSError as exc:
        if exc.errno == 48 or "in use" in str(exc).lower():
            raise RuntimeError(
                f"port {port} is already in use — stop the other server or pass a different --port."
            ) from exc
        raise

    with httpd:
        url = f"http://localhost:{port}/{SDAG_HTML}"
        log.info("serving %s on %s (Ctrl-C to stop)", output_dir, url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            log.info("shutting down")
