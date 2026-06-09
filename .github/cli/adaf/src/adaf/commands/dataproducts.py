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
import subprocess
from pathlib import Path

# Third Party
import yaml

# Local
from adaf import config, viewer
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
    """Run ``dbt parse`` to refresh target/manifest.json (fail loud)."""
    cwd = cwd or config.PROJECT_ROOT
    proc = subprocess.run(["dbt", "parse"], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"`dbt parse` failed (exit {proc.returncode}):\n{proc.stderr or proc.stdout}")


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
    """unique_ids dbt resolves for the named selector — full grammar, via ``dbt ls``."""
    cwd = cwd or config.PROJECT_ROOT
    cmd = ["dbt", "ls", "--quiet", "--selector", name, "--output", "json", "--output-keys", "unique_id"]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(
            f"`dbt ls --selector {name}` failed (exit {proc.returncode}):\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    uids: set[str] = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        uids.add(json.loads(line)["unique_id"])
    return uids


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


def _build_viewer_graphs(args) -> tuple[dict, dict, str]:
    """Resolve selectors, read the full manifest, and build the two Cytoscape JSON payloads."""
    if getattr(args, "parse", False):
        dbt_parse()
    nodes, edges = viewer.load_full_manifest(args.manifest)
    named_selectors = _filter_named(load_selector_names(args.selectors), list(args.product or []), args.selectors)
    resolved = {name: resolve_members(name) for name, _desc in named_selectors}
    full_json = viewer.build_full_graph_json(nodes, edges, resolved)
    super_json = viewer.build_super_graph_json(nodes, edges, resolved)
    source_label = str(args.manifest)
    return full_json, super_json, source_label


def cmd_generate(args) -> int:
    full_json, super_json, source_label = _build_viewer_graphs(args)
    build_id = viewer.write_outputs(args.output, full_json, super_json, source_label=source_label)
    log.info("sdag assets written to %s (build_id=%s)", args.output, build_id)
    log.info("open %s/%s in a browser, or run `products serve` to host it", args.output, viewer.SDAG_HTML)
    return 0


def cmd_serve(args) -> int:
    cmd_generate(args)  # always regenerate first so the served bundle is fresh
    viewer.serve(args.output, args.port)
    return 0
