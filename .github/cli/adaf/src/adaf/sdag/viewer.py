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
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# Local
from adaf.dbt import cache
from adaf.dbt.manifest_view import ManifestView

log = logging.getLogger(__name__)

# Template assets ship inside the package (resolved relative to THIS file, not cwd — the package is
# imported via cwd-on-path but its assets are package-relative).
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

FULL_GRAPH_JSON = "full_graph.json"
SUPER_GRAPH_JSON = "super_graph.json"
SDAG_HTML = "sdag.html"
SDAG_JS = "sdag.js"
# Externalised brand design tokens (T35) — the canvas palette/fonts/RAG
# thresholds sdag.js fetches at runtime. Shipped verbatim (not templated)
# alongside the other assets; embedded on window.__SDAG_TOKENS__ for --inline.
DESIGN_TOKENS_JSON = "design-tokens.json"

# Every file a generated viewer may emit. ``write_archive`` bundles whichever of these are present
# in the output dir — a multi-file build carries all five; an ``--inline`` build carries only the
# one self-contained ``sdag.html``.
VIEWER_FILES: tuple[str, ...] = (SDAG_HTML, SDAG_JS, FULL_GRAPH_JSON, SUPER_GRAPH_JSON, DESIGN_TOKENS_JSON)

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


# ─── Governance facts per node (docs / tests / semantic backing) ─────────────


def node_governance(view: ManifestView) -> dict[str, dict[str, Any]]:
    """Per-node governance facts the viewer surfaces on selection/hover (see T21).

    For every data node (model/source/seed/snapshot/…) compute three at-a-glance signals straight
    from the manifest the viewer already parsed — no extra I/O, no dbt:

    * ``has_description`` — does the node carry a non-empty ``description`` (doc coverage)?
    * ``test_count`` / ``test_types`` — how many ``test`` nodes target it, and the distinct kinds
      (``not_null`` / ``unique`` / ``relationships`` / … from ``test_metadata.name``; singular/custom
      tests bucket as ``singular``). A test is attributed to its ``attached_node`` when dbt records
      one, else to every model in its ``depends_on.nodes`` (relationship tests touch two models).
    * ``semantic_backed`` — does a ``semantic_models`` entry build on this node (its
      ``depends_on.nodes``)?
    """
    test_count: dict[str, int] = defaultdict(int)
    test_types: dict[str, set[str]] = defaultdict(set)
    for rec in view.of_type("test").values():
        meta = rec.raw.get("test_metadata") or {}
        tname = meta.get("name") or "singular"
        attached = rec.raw.get("attached_node")
        targets = [attached] if attached else (rec.raw.get("depends_on") or {}).get("nodes", [])
        for uid in targets:
            if not uid:
                continue
            test_count[uid] += 1
            test_types[uid].add(str(tname))

    semantic_backed: set[str] = set()
    for sem in view.section("semantic_models").values():
        for uid in (sem.get("depends_on") or {}).get("nodes", []):
            semantic_backed.add(uid)

    gov: dict[str, dict[str, Any]] = {}
    for uid, rec in view.records().items():
        gov[uid] = {
            "has_description": bool((rec.raw.get("description") or "").strip()),
            "test_count": test_count.get(uid, 0),
            "test_types": sorted(test_types.get(uid, set())),
            "semantic_backed": uid in semantic_backed,
        }
    return gov


# ─── Per-selector compliance (read back the cache T19 enriched) ──────────────


def load_selector_compliance(root: Path, names: list[str]) -> dict[str, dict[str, Any]]:
    """Read each named selector's compliance rollup + per-node annotations from its cache file.

    ``adaf.sdag.annotations.enrich_all`` runs in the generate flow BEFORE this, writing the
    ``compliance`` rollup and per boundary-node ``annotations`` into each selector's cache file
    (``tmp/adaf_cache/selectors/<selector>.json``). This reads them straight back so the viewer can
    embed them in ``full_graph.json`` — the page renders a product's compliance with no extra fetch.

    Returns ``{selector: {"compliance": {...rollup...}, "annotations": {uid: {...}}}}`` for every
    selector whose cache file carries compliance. A cache file with neither key (a product with no
    boundary obligations) is simply omitted from the map.
    """
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        path = cache.selector_cache_path(root, name)
        if not path.exists():
            continue
        blob = json.loads(path.read_text(encoding="utf-8"))
        compliance = blob.get("compliance")
        annotations = blob.get("annotations")
        if compliance is None and annotations is None:
            continue
        out[name] = {"compliance": compliance or {}, "annotations": annotations or {}}
    return out


# ─── Full-manifest load (everything, not just data nodes) ────────────────────


def display_graph(view: ManifestView) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]]]:
    """Project a :class:`ManifestView` into the viewer's ``(nodes, edges)`` over EVERY data section.

    ``nodes`` maps unique_id → display attrs; ``edges`` are the view's ``parent_map`` edges filtered
    to present endpoints (drops references to disabled/deferred/external resources). Unlike
    ``graph.Graph``, NO resource-type filtering happens — the viewer shows everything (tests,
    semantic models, …), so it keeps all of the view's records.
    """
    governance = node_governance(view)
    nodes: dict[str, dict[str, Any]] = {}
    for uid, rec in view.records().items():
        node = rec.raw
        raw_tags = node.get("tags")
        raw_fqn = node.get("fqn")
        tags: list[Any] = raw_tags if isinstance(raw_tags, list) else []
        fqn: list[Any] = raw_fqn if isinstance(raw_fqn, list) else []
        gov = governance.get(uid, {})
        nodes[uid] = {
            "unique_id": uid,
            "resource_type": rec.resource_type,
            "name": node.get("name") or uid.rsplit(".", 1)[-1],
            "fqn": [str(p) for p in fqn],
            "tags": [str(t) for t in tags],
            "materialized": (node.get("config") or {}).get("materialized"),
            "schema": node.get("schema"),
            # Governance signals (T21) — surfaced on node selection/hover in the viewer.
            "has_description": gov.get("has_description", False),
            "test_count": gov.get("test_count", 0),
            "test_types": gov.get("test_types", []),
            "semantic_backed": gov.get("semantic_backed", False),
        }

    # Exposures are downstream consumers (not in ``view.records()``): include them so the boundary
    # classification can see a model feeding an external exposure as an OUTBOUND edge, and so the
    # node-type filter can hide/show them. They carry no test/semantic governance of their own.
    for uid, exp in view.section("exposures").items():
        raw_fqn = exp.get("fqn")
        raw_tags = exp.get("tags")
        nodes[uid] = {
            "unique_id": uid,
            "resource_type": "exposure",
            "name": exp.get("name") or uid.rsplit(".", 1)[-1],
            "fqn": [str(p) for p in (raw_fqn if isinstance(raw_fqn, list) else [])],
            "tags": [str(t) for t in (raw_tags if isinstance(raw_tags, list) else [])],
            "materialized": None,
            "schema": None,
            "has_description": bool((exp.get("description") or "").strip()),
            "test_count": 0,
            "test_types": [],
            "semantic_backed": False,
        }

    # parent_edges(present) keeps only edges whose BOTH endpoints are present — passing the node set
    # (data records + exposures) lets the model->exposure edges through while still dropping refs to
    # disabled/deferred/external resources.
    edges = view.parent_edges(set(nodes))
    log.debug("viewer manifest: %d nodes (incl. exposures), %d edges", len(nodes), len(edges))
    return nodes, edges


def load_full_manifest(path: Path | str) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]]]:
    """Read manifest.json into the viewer's ``(nodes, edges)`` (wrapper over :func:`display_graph`)."""
    return display_graph(ManifestView.load(path))


# ─── Cytoscape JSON builders (pure) ──────────────────────────────────────────


def _primary_selector(memberships: list[str], sel_size: dict[str, int]) -> str | None:
    """Pick the smallest matching selector (most specific) as the compound parent."""
    if not memberships:
        return None
    return min(memberships, key=lambda s: (sel_size.get(s, 0), s))


def _full_selector_compounds(
    resolved: dict[str, set[str]],
    nodes: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """One compound parent node per non-empty selector (selectors with no present member skipped)."""
    compounds: list[dict[str, Any]] = []
    for sel_name, members in resolved.items():
        present = [uid for uid in members if uid in nodes]
        if not present:
            continue
        compounds.append(
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
    return compounds


def _full_unmatched_compound(unmatched_uids: list[str]) -> list[dict[str, Any]]:
    """Catch-all compound for nodes matched by no selector (empty list when none are unmatched)."""
    if not unmatched_uids:
        return []
    return [
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
    ]


def _full_entity_nodes(
    nodes: dict[str, dict[str, Any]],
    node_to_selectors: dict[str, list[str]],
    sel_size: dict[str, int],
) -> list[dict[str, Any]]:
    """Leaf entity nodes, each parented to its primary (smallest) selector or the catch-all."""
    entities: list[dict[str, Any]] = []
    for uid, attrs in nodes.items():
        memberships = node_to_selectors.get(uid, [])
        primary = _primary_selector(memberships, sel_size)
        parent_id = f"sel::{primary}" if primary else f"sel::{UNMATCHED_ID}"
        rt = attrs.get("resource_type") or ""
        entities.append(
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
                    # Governance signals (T21) carried onto the leaf node so the viewer can render
                    # docs/tests/semantic backing on selection + hover without a second lookup.
                    "has_description": attrs.get("has_description", False),
                    "test_count": attrs.get("test_count", 0),
                    "test_types": attrs.get("test_types") or [],
                    "semantic_backed": attrs.get("semantic_backed", False),
                },
                "classes": f"entity entity-{rt}",
            }
        )
    return entities


def _full_lineage_edges(edges: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Lineage edge elements, one per manifest ``(parent, child)`` edge."""
    return [
        {
            "data": {
                "id": f"e::{parent_uid}->{child_uid}",
                "source": parent_uid,
                "target": child_uid,
                "kind": "lineage",
            },
            "classes": "edge-lineage",
        }
        for parent_uid, child_uid in edges
    ]


def build_full_graph_json(
    nodes: dict[str, dict[str, Any]],
    edges: list[tuple[str, str]],
    resolved: dict[str, set[str]],
    compliance: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Cytoscape JSON: every entity + every edge, grouped by compound selector nodes.

    A node matching multiple selectors is placed inside the smallest (most specific) one as its
    ``parent``; the full membership list is also stored on ``data.selectors`` so the viewer can
    highlight every containing selector when the node is tapped.

    ``compliance`` (when given) is the per-selector rollup + per-node annotations from
    :func:`load_selector_compliance`; it is embedded under ``metadata.compliance`` so the viewer can
    render a product's compliance panel + per-node pass/fail badges straight from this one payload.
    """
    node_to_selectors: dict[str, list[str]] = defaultdict(list)
    for sel_name, members in resolved.items():
        for uid in members:
            if uid in nodes:
                node_to_selectors[uid].append(sel_name)

    sel_size = {name: len(members) for name, members in resolved.items()}
    unmatched_uids = [uid for uid in nodes if uid not in node_to_selectors]

    elements: list[dict[str, Any]] = []
    elements.extend(_full_selector_compounds(resolved, nodes))
    elements.extend(_full_unmatched_compound(unmatched_uids))
    elements.extend(_full_entity_nodes(nodes, node_to_selectors, sel_size))
    elements.extend(_full_lineage_edges(edges))

    return {
        "elements": elements,
        "metadata": {
            "n_nodes": len(nodes),
            "n_edges": len(edges),
            "n_selectors": sum(1 for members in resolved.values() if any(uid in nodes for uid in members)),
            "n_unmatched_nodes": len(unmatched_uids),
            "compliance": compliance or {},
        },
    }


def _super_membership_maps(
    nodes: dict[str, dict[str, Any]],
    resolved: dict[str, set[str]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build ``uid -> supers`` (selectors + catch-all) and its inverse ``super -> member uids``."""
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

    return uid_to_supers, super_members


def _super_node_elements(
    nodes: dict[str, dict[str, Any]],
    super_members: dict[str, list[str]],
    definitions: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """One super-node per selector, with a resource_type breakdown Counter and log1p sizing.

    ``definitions[sname]`` (a selector's resolution rule, e.g. ``tag:demand``) is embedded on the
    super-node so the viewer sidebar can explain why nodes belong to the product."""
    defs = definitions or {}
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
                    # The selector's resolution rule (empty for the synthetic unmatched bucket).
                    "definition": defs.get(sname, ""),
                },
                "classes": "super" + (" unmatched" if sname == UNMATCHED_ID else ""),
            }
        )
    return elements


def _super_edge_counts(
    edges: list[tuple[str, str]],
    uid_to_supers: dict[str, list[str]],
    super_members: dict[str, list[str]],
) -> tuple[Counter[tuple[str, str, str]], int]:
    """Aggregate cross-super edges and tally fully-internal ones.

    An edge (parent, child) contributes to super-edge (ps, cs) iff ps != cs AND the edge is not
    internal to BOTH ps and cs (the latter prevents phantom edges between overlapping selectors).
    The returned ``internal_edges`` counts manifest edges that crossed nothing.
    """
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
    return edge_counts, internal_edges


def _super_edge_elements(edge_counts: Counter[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """Cross-super edge elements with ``count`` and log1p-weighted ``log_count``."""
    return [
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
        for (src, tgt, kind), count in edge_counts.items()
    ]


def build_super_graph_json(
    nodes: dict[str, dict[str, Any]],
    edges: list[tuple[str, str]],
    resolved: dict[str, set[str]],
    definitions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Collapse each selector into a super-node; aggregate cross-selector edges.

    A unique_id may belong to multiple selectors — every membership contributes to that selector's
    super-node, and each manifest edge fans out across the cross-product of (source-memberships ×
    target-memberships). Identical ``(src_super, tgt_super, kind)`` triples collapse to one edge with a
    ``count``. Edges that stay inside one super (or inside the intersection of two overlapping supers)
    are dropped as internal and tallied in metadata.
    """
    uid_to_supers, super_members = _super_membership_maps(nodes, resolved)

    edge_counts, internal_edges = _super_edge_counts(edges, uid_to_supers, super_members)

    elements: list[dict[str, Any]] = []
    elements.extend(_super_node_elements(nodes, super_members, definitions))
    elements.extend(_super_edge_elements(edge_counts))

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
    tokens_src = assets_dir / DESIGN_TOKENS_JSON
    for template in (html_tpl, js_tpl, tokens_src):
        if not template.exists():
            raise FileNotFoundError(f"viewer template missing at {template}")
    output_dir.mkdir(parents=True, exist_ok=True)

    build_id = _build_id()
    for graph in (full_graph, super_graph):
        graph["metadata"]["build_id"] = build_id
        graph["metadata"]["source"] = source_label

    (output_dir / FULL_GRAPH_JSON).write_text(json.dumps(full_graph, indent=2), encoding="utf-8")
    (output_dir / SUPER_GRAPH_JSON).write_text(json.dumps(super_graph, indent=2), encoding="utf-8")
    # Ship the design tokens verbatim — they are NOT templated (no build-id swap).
    (output_dir / DESIGN_TOKENS_JSON).write_text(tokens_src.read_text(encoding="utf-8"), encoding="utf-8")
    (output_dir / SDAG_HTML).write_text(
        _apply_tokens(html_tpl.read_text(encoding="utf-8"), build_id=build_id, source_label=source_label),
        encoding="utf-8",
    )
    (output_dir / SDAG_JS).write_text(
        _apply_tokens(js_tpl.read_text(encoding="utf-8"), build_id=build_id, source_label=source_label),
        encoding="utf-8",
    )
    log.info(
        "wrote %s, %s, %s, %s, %s into %s (build_id=%s)",
        FULL_GRAPH_JSON,
        SUPER_GRAPH_JSON,
        DESIGN_TOKENS_JSON,
        SDAG_HTML,
        SDAG_JS,
        output_dir,
        build_id,
    )
    return build_id


# The HTML line that pulls in the external JS; replaced wholesale in inline mode.
_JS_INCLUDE = '<script src="sdag.js?v={{BUILD_ID}}" defer></script>'


def write_inline(
    output_dir: Path,
    full_graph: dict[str, Any],
    super_graph: dict[str, Any],
    *,
    source_label: str,
    assets_dir: Path = ASSETS_DIR,
) -> str:
    """Write ONE standalone ``sdag.html`` with the JS and both graphs inlined; return build id.

    The graphs are embedded on ``window.__SDAG_DATA__`` (which ``fetchView`` prefers over a
    network fetch), and the external ``<script src="sdag.js">`` include is replaced by the JS
    inline. The result opens directly over ``file://`` with no sidecar files or web server.
    """
    html_tpl = assets_dir / SDAG_HTML
    js_tpl = assets_dir / SDAG_JS
    tokens_src = assets_dir / DESIGN_TOKENS_JSON
    for template in (html_tpl, js_tpl, tokens_src):
        if not template.exists():
            raise FileNotFoundError(f"viewer template missing at {template}")
    output_dir.mkdir(parents=True, exist_ok=True)

    build_id = _build_id()
    for graph in (full_graph, super_graph):
        graph["metadata"]["build_id"] = build_id
        graph["metadata"]["source"] = source_label

    # Embed both graphs as a JS global. Escape `</` so a stray "</script>" inside any string
    # value (node names, tags) can't terminate the inline <script> early.
    data_json = json.dumps({"full": full_graph, "super": super_graph}).replace("</", "<\\/")
    data_script = f"<script>window.__SDAG_DATA__ = {data_json};</script>"
    # Embed the design tokens too so loadTokens() prefers the global over a (file://) fetch.
    tokens_json = tokens_src.read_text(encoding="utf-8").replace("</", "<\\/")
    tokens_script = f"<script>window.__SDAG_TOKENS__ = {tokens_json};</script>"
    inline_js = "<script>\n" + js_tpl.read_text(encoding="utf-8") + "\n</script>"

    html = html_tpl.read_text(encoding="utf-8")
    if _JS_INCLUDE not in html:
        raise RuntimeError(f"sdag.html template is missing the expected JS include line: {_JS_INCLUDE!r}")
    html = html.replace(_JS_INCLUDE, f"{tokens_script}\n{data_script}\n{inline_js}")
    html = _apply_tokens(html, build_id=build_id, source_label=source_label)

    out = output_dir / SDAG_HTML
    out.write_text(html, encoding="utf-8")
    log.info("wrote standalone %s (%d KiB, build_id=%s)", out, len(html) // 1024, build_id)
    return build_id


def write_archive(output_dir: Path, zip_path: Path) -> list[str]:
    """Bundle the generated viewer in ``output_dir`` into a portable ``.zip`` at ``zip_path``.

    Zips every viewer asset present in ``output_dir`` (``sdag.html``, ``sdag.js``, the two graph
    JSONs and ``design-tokens.json``) at the archive root, preserving the flat layout the page
    fetches so a recipient can unzip and serve it standalone. The per-selector compliance the page
    needs is already embedded in ``full_graph.json`` (see :func:`build_full_graph_json`), so no
    sidecar cache files are required. Pair generation with ``--inline`` for the most portable
    archive: the output dir then holds only one self-contained ``sdag.html`` that opens over
    ``file://`` with no server. Returns the sorted archive entry names.

    Fails loud (``FileNotFoundError``) if ``output_dir`` is missing or holds no viewer assets — an
    empty archive is a generation bug, not a degraded success.
    """
    if not output_dir.is_dir():
        raise FileNotFoundError(f"sdag output dir does not exist: {output_dir} — generate the viewer first")
    present = [name for name in VIEWER_FILES if (output_dir / name).is_file()]
    if not present:
        raise FileNotFoundError(f"no sdag viewer assets found in {output_dir} — nothing to archive")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in present:
            zf.write(output_dir / name, arcname=name)
    log.info(
        "wrote sdag archive %s (%d entr%s: %s)",
        zip_path,
        len(present),
        "y" if len(present) == 1 else "ies",
        ", ".join(present),
    )
    return sorted(present)


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
