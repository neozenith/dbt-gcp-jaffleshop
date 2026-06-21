"""``products boundaries`` — classify each node of a data product as a system-boundary node, and
``check system-boundaries`` — gate each boundary node on the per-class artifacts it owes.

A "data product" is a NAMED selector in ``selectors.yml`` (e.g. ``supply``, ``demand``). Its
membership is whatever dbt itself resolves for that selector — including graph-operator expansion
(``+model`` pulls in upstream sources) — so we ask dbt via ``dbt ls --selector <name> --output json``
rather than re-implementing the selector grammar.

For each product we load the data-lineage DAG from ``manifest.json`` (``graph.py``), restrict the
membership to data nodes, and classify every member as a system-boundary node — inbound / outbound /
both — or internal. The result dataclasses live in ``adaf.reports.dataproducts`` (re-exported here).
"""

# Standard Library
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Third Party
import yaml

# Local
from adaf import annotations, config, viewer
from adaf.dbt import cache, ls, runner
from adaf.dbt.manifest_view import ManifestView
from adaf.dbt.selectors import load_selectors
from adaf.graph import Graph, classify_boundary
from adaf.reports.dataproducts import (
    BoundaryReport,
    BoundaryTestRow,
    MemberRow,
    ProductBoundary,
    SystemBoundaryReport,
)
from adaf.taxonomy import NodeFacts, load_node_facts
from adaf.utils.formatting import render_from_args

log = logging.getLogger(__name__)

# Sentinel for a bare ``--archive`` (no path): write the zip next to the assets as
# ``<output>/sdag.zip``. argparse stores this when the flag is given with no value (``const=``).
ARCHIVE_DEFAULT = "<output>/sdag.zip"

# `dbt ls` spawns a full dbt parse per call; cap concurrency so resolving many selectors doesn't
# exhaust memory. IO/subprocess-bound, so a small pool still wins big.
_MAX_LS_WORKERS = min(12, (os.cpu_count() or 4))

__all__ = [
    "BoundaryReport",
    "BoundaryTestRow",
    "MemberRow",
    "ProductBoundary",
    "SystemBoundaryReport",
    "dbt_parse",
    "load_graph",
    "load_selector_names",
    "resolve_members",
    "evaluate",
    "cmd",
    "required_artifacts",
    "load_exposure_targets",
    "load_semantic_model_targets",
    "evaluate_system_boundaries",
    "cmd_check",
    "cmd_generate",
    "cmd_serve",
]


# ─── I/O: manifest graph, selector names, selector membership ────────────────


def dbt_parse(cwd: Path | None = None) -> None:
    """Run ``dbt parse`` to refresh target/manifest.json (fail loud).

    Thin wrapper over :func:`adaf.dbt.runner.dbt_parse` (the single dbt entry point); kept as a named
    function here so the ``products``/``check`` call sites and ``__all__`` re-export are unchanged.
    """
    runner.dbt_parse(cwd)


def load_graph(path: Path | str, *, parse: bool = False, cwd: Path | None = None) -> Graph:
    """Load the lineage graph from manifest.json, optionally refreshing via ``dbt parse`` first."""
    if parse:
        dbt_parse(cwd)
    if not Path(path).exists():
        raise FileNotFoundError(f"dbt manifest not found at '{path}'. Run `dbt parse` or pass --parse.")
    return Graph.load(path)


def load_selector_names(path: Path | str) -> list[tuple[str, str]]:
    """Read the named selectors from ``selectors.yml`` → ``[(name, description), ...]`` (fail loud)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"selectors file not found at '{p}'. Expected dbt's selectors.yml.")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    sels = data.get("selectors") or []
    if not isinstance(sels, list):
        raise ValueError(f"selectors.yml: top-level `selectors` must be a list, got {type(sels).__name__}")
    names: list[tuple[str, str]] = []
    for sel in sels:
        name = sel.get("name") if isinstance(sel, dict) else None
        if not name:
            raise ValueError(f"selector missing `name`: {sel!r}")
        names.append((name, (sel.get("description") or "").strip()))
    return names


def resolve_members(name: str, *, cwd: Path | None = None) -> set[str]:
    """unique_ids dbt resolves for the named selector — full grammar, via ``dbt ls``.

    Thin wrapper over :func:`adaf.dbt.ls.ls_member_ids` (the single ``dbt ls`` home); kept as a named
    function here so existing call sites and ``__all__`` re-export are unchanged.
    """
    return ls.ls_member_ids(name, cwd=cwd)


# ─── products boundaries: evaluate + handler ─────────────────────────────────


def evaluate(graph: Graph, named_selectors: list[tuple[str, str]]) -> BoundaryReport:
    """Resolve each named selector to its members and classify them against the graph."""
    data_nodes = set(graph.nodes())
    products: list[ProductBoundary] = []
    for name, description in named_selectors:
        members = resolve_members(name) & data_nodes
        classified = classify_boundary(members, graph.edges())
        rows: list[MemberRow] = []
        for uid, nb in classified.items():
            info = graph.info(uid)
            rows.append(
                MemberRow(
                    unique_id=uid,
                    name=info.name if info else uid.rsplit(".", 1)[-1],
                    resource_type=info.resource_type if info else "?",
                    classification=nb.classification,
                    external_parents=nb.external_parents,
                    external_children=nb.external_children,
                )
            )
        log.debug("data product %-12s → %3d node(s) classified", name, len(rows))
        products.append(ProductBoundary(name, description, rows))
    scope = f"{len(products)} data product(s) from {config.DEFAULT_SELECTORS}"
    return BoundaryReport(products, scope=scope)


def _filter_named(named_selectors: list[tuple[str, str]], wanted: list[str], selectors_path) -> list[tuple[str, str]]:
    """Narrow the named selectors to ``--product`` if given; fail loud on an unknown name."""
    if not wanted:
        return named_selectors
    known = {name for name, _ in named_selectors}
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise RuntimeError(
            f"unknown data product(s): {', '.join(unknown)}. "
            f"Defined in {selectors_path}: {', '.join(sorted(known)) or '(none)'}"
        )
    return [(name, desc) for name, desc in named_selectors if name in wanted]


def _select_named(args) -> tuple[Graph, list[tuple[str, str]]]:
    """Load the graph + the named selectors, narrowed to ``--product`` if given."""
    graph = load_graph(args.manifest, parse=getattr(args, "parse", False))
    named_selectors = _filter_named(load_selector_names(args.selectors), list(args.product or []), args.selectors)
    return graph, named_selectors


def cmd(args) -> int:
    graph, named_selectors = _select_named(args)
    return render_from_args(evaluate(graph, named_selectors), args)


# ─── check system-boundaries: gate boundary nodes on their per-class artifacts ─


# A published OUTBOUND model is a contract with downstream consumers, so it must declare its full
# dbt-native interface; an INBOUND source is data you don't own, so prove it's arriving on time.
#   outbound model  → enforced contract + a dbt exposure naming the consumer + a semantic_model
#   inbound source  → a freshness SLA  (and we additionally SUGGEST good tests — see _inbound_suggestions)
def required_artifacts(classification: str, resource_type: str) -> list[str]:
    req: list[str] = []
    if classification in ("inbound", "both") and resource_type == "source":
        req.append("freshness")
    if classification in ("outbound", "both") and resource_type == "model":
        req += ["contract", "exposure", "semantic_model"]
    return req


def load_exposure_targets(manifest_path: Path | str) -> set[str]:
    """unique_ids of every node referenced by an ``exposures:`` block (its ``depends_on.nodes``)."""
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    targets: set[str] = set()
    for exp in (data.get("exposures") or {}).values():
        targets.update((exp.get("depends_on") or {}).get("nodes", []))
    return targets


def load_semantic_model_targets(manifest_path: Path | str) -> set[str]:
    """unique_ids of every model a ``semantic_models:`` entry is defined on (its ``depends_on.nodes``)."""
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    targets: set[str] = set()
    for sm in (data.get("semantic_models") or {}).values():
        targets.update((sm.get("depends_on") or {}).get("nodes", []))
    return targets


def _inbound_suggestions(nf: NodeFacts | None) -> list[str]:
    """Deterministic, advisory test recommendations for an inbound boundary node (source OR the
    product's entry-point model), derived from its columns + tests. Not gated — guidance for hardening
    the data the product depends on: key columns at an entry point should carry unique + not_null."""
    if nf is None:
        return []
    out: list[str] = []
    for col in nf.id_columns():
        want = [t for t in ("unique", "not_null") if t not in nf.tests_on(col)]
        if want:
            out.append(f"add {', '.join(want)} on key `{col}`")
    if nf.resource_type == "source" and not nf.has_freshness:
        out.append("declare a freshness SLA (loaded_at_field + warn_after/error_after)")
    return out


def _missing_artifacts(
    uid: str,
    classification: str,
    resource_type: str,
    facts: dict[str, NodeFacts] | None,
    exposures: set[str] | None,
    semantic: set[str] | None,
) -> tuple[list[str], list[str]]:
    """(required, missing) artifacts for a boundary node. With no facts, nothing is required
    (preserves the legacy ≥1-test-only gate for callers that don't pass the extra context)."""
    required = required_artifacts(classification, resource_type)
    if not required or facts is None:
        return ([] if facts is None else required), []
    nf = facts.get(uid)
    missing: list[str] = []
    for art in required:
        if art == "freshness" and not (nf and nf.has_freshness):
            missing.append(art)
        elif art == "contract" and not (nf and nf.contract_enforced):
            missing.append(art)
        elif art == "exposure" and uid not in (exposures or set()):
            missing.append(art)
        elif art == "semantic_model" and uid not in (semantic or set()):
            missing.append(art)
    return required, missing


def evaluate_system_boundaries(
    graph: Graph,
    named_selectors: list[tuple[str, str]],
    *,
    node_facts: dict[str, NodeFacts] | None = None,
    exposure_targets: set[str] | None = None,
    semantic_model_targets: set[str] | None = None,
) -> SystemBoundaryReport:
    """Classify each product's nodes; emit a row per BOUNDARY node with its test count, the per-class
    artifacts it owes (outbound: contract/exposure/semantic_model; inbound: freshness), and advisory
    test suggestions for inbound nodes. When ``node_facts`` is omitted the gate degrades to the legacy
    ≥1-test check (used by the existing unit tests)."""
    data_nodes = set(graph.nodes())
    rows: list[BoundaryTestRow] = []
    for name, _description in named_selectors:
        members = resolve_members(name) & data_nodes
        classified = classify_boundary(members, graph.edges())
        for uid, nb in classified.items():
            if not nb.is_boundary:
                continue  # internal nodes are interior to the product — not gated
            info = graph.info(uid)
            resource_type = info.resource_type if info else "?"
            required, missing = _missing_artifacts(
                uid, nb.classification, resource_type, node_facts, exposure_targets, semantic_model_targets
            )
            suggestions = (
                _inbound_suggestions((node_facts or {}).get(uid)) if nb.classification in ("inbound", "both") else []
            )
            rows.append(
                BoundaryTestRow(
                    product=name,
                    unique_id=uid,
                    name=info.name if info else uid.rsplit(".", 1)[-1],
                    resource_type=resource_type,
                    classification=nb.classification,
                    test_count=info.test_count if info else 0,
                    required=required,
                    missing=missing,
                    suggestions=suggestions,
                )
            )
    scope = f"system boundaries of {len(named_selectors)} data product(s)"
    return SystemBoundaryReport(scope, rows)


def cmd_check(args) -> int:
    graph, named_selectors = _select_named(args)
    facts = {n.unique_id: n for n in load_node_facts(args.manifest)}
    return render_from_args(
        evaluate_system_boundaries(
            graph,
            named_selectors,
            node_facts=facts,
            exposure_targets=load_exposure_targets(args.manifest),
            semantic_model_targets=load_semantic_model_targets(args.manifest),
        ),
        args,
    )


# ─── products generate / serve: the interactive sdag viewer ──────────────────


def _maybe_parse(args) -> None:
    """`dbt parse` only when warranted: never with --no-parse; otherwise only if the manifest is
    stale (a source file is newer than it). Avoids the slow reparse on a clean tree."""
    if not getattr(args, "parse", True):  # --no-parse: trust the existing manifest
        log.debug("sdag: --no-parse — using the existing manifest as-is")
        return
    if cache.manifest_is_fresh(args.manifest, config.project_root()):
        log.info("sdag: manifest is fresh (no source newer than it) — skipping `dbt parse`")
        return
    log.info("sdag: manifest stale or missing — running `dbt parse`")
    dbt_parse()


def _resolve_all(static: list[tuple[str, str]], args, view: ManifestView) -> dict[str, set[str]]:
    """Resolve every static selector to its member ids — cache hits skip ``dbt ls``; the misses are
    resolved in parallel (bounded pool), with per-selector progress logging.

    On a miss, each selector's members are classified against the lineage graph and the membership +
    boundary annotation is persisted to that selector's own cache file."""
    root = config.project_root()
    resolved: dict[str, set[str]] = {}
    todo: list[str] = []
    for name, _desc in static:
        entry = cache.load_selector(root, args.manifest, args.selectors, name)
        if entry is not None:
            resolved[name] = entry.members
        else:
            todo.append(name)
    log.info(
        "sdag: %d/%d selector(s) served from cache; resolving %d via `dbt ls`", len(resolved), len(static), len(todo)
    )
    if todo:
        graph = Graph.from_view(view)  # the lineage graph is needed only for the misses
        done = 0
        with ThreadPoolExecutor(max_workers=min(_MAX_LS_WORKERS, len(todo))) as pool:
            futures = {pool.submit(ls.ls_member_ids, name): name for name in todo}
            for future in as_completed(futures):
                name = futures[future]
                members = future.result()  # propagates a failed `dbt ls` (fail loud)
                resolved[name] = members
                boundaries = graph.classify(members)
                cache.save_selector(
                    root, args.manifest, args.selectors, name, cache.SelectorCacheEntry(members, boundaries)
                )
                done += 1
                log.info("sdag: [%d/%d] resolved selector %s (%d members)", done, len(todo), name, len(members))
    return resolved


def _build_viewer_graphs(args) -> tuple[dict, dict, str]:
    """Resolve every (static, --product-filtered) named selector, read the full manifest, and build
    the two Cytoscape JSON payloads — enriching each selector's cache with sdag-check compliance so
    the viewer can render per-product compliance + per-node governance straight from the payload."""
    _maybe_parse(args)
    view = ManifestView.load(args.manifest)  # parse once; the viewer + boundary classify share it
    nodes, edges = viewer.display_graph(view)
    # A state:modified selector is a PR-diff selector, not a static data product — `dbt ls` errors on
    # it without --state — so the viewer can only render the static selectors.
    selectors = load_selectors(args.selectors)
    wanted = list(getattr(args, "product", None) or [])
    static = [
        (name, desc) for name, desc, uses_state, _def in selectors if not uses_state and (not wanted or name in wanted)
    ]
    skipped = [name for name, _desc, uses_state, _def in selectors if uses_state]
    definitions = {name: definition for name, _desc, uses_state, definition in selectors if not uses_state}
    if skipped:
        log.warning("sdag: skipping %d state-based selector(s) not renderable without --state: %s",
                    len(skipped), ", ".join(skipped))
    resolved = _resolve_all(static, args, view)
    root = config.project_root()
    annotations.enrich_all(root, view, resolved)  # adds compliance rollup + per-node annotations to the cache
    compliance = viewer.load_selector_compliance(root, list(resolved))
    full_json = viewer.build_full_graph_json(nodes, edges, resolved, compliance)
    super_json = viewer.build_super_graph_json(nodes, edges, resolved, definitions=definitions)
    log.info("sdag: built graphs — %d nodes / %d edges across %d selector(s)", len(nodes), len(edges), len(resolved))
    return full_json, super_json, str(args.manifest)


def _archive_path(args) -> Path | None:
    """Resolve ``--archive`` to a zip path, or ``None`` when not requested. Bare ``--archive`` →
    ``<output>/sdag.zip``; ``--archive PATH`` → ``PATH``."""
    archive = getattr(args, "archive", None)
    if archive is None:
        return None
    return args.output / "sdag.zip" if archive == ARCHIVE_DEFAULT else Path(archive)


def cmd_generate(args) -> int:
    full_json, super_json, source_label = _build_viewer_graphs(args)
    if getattr(args, "inline", False):
        build_id = viewer.write_inline(args.output, full_json, super_json, source_label=source_label)
        target = args.output / viewer.SDAG_HTML
        print(f"sdag standalone written to {target} (build_id={build_id})", file=sys.stderr)
        print(f"open {target} directly in a browser — no server needed (inline)", file=sys.stderr)
    else:
        build_id = viewer.write_outputs(args.output, full_json, super_json, source_label=source_label)
        print(f"sdag assets written to {args.output} (build_id={build_id})", file=sys.stderr)
        print("run `adaf products serve` to host it (the multi-file viewer needs a server, not file://)",
              file=sys.stderr)
    zip_path = _archive_path(args)
    if zip_path is not None:
        entries = viewer.write_archive(args.output, zip_path)
        print(f"sdag archive written to {zip_path} ({len(entries)} entries: {', '.join(entries)})", file=sys.stderr)
    return 0


def cmd_serve(args) -> int:
    cmd_generate(args)  # always regenerate first so the served bundle is fresh
    viewer.serve(args.output, args.port)
    return 0
