"""``products boundaries`` — classify each node of a data product as a system-boundary node.

A "data product" is a NAMED selector in ``selectors.yml`` (e.g. ``supply``, ``demand``). Its
membership is whatever dbt itself resolves for that selector — including graph-operator expansion
(``+model`` pulls in upstream sources) — so we ask dbt via ``dbt ls --selector <name> --output json``
rather than re-implementing the selector grammar (mirrors ``selection.py``'s ``--select`` path, and
deliberately unlike a hand-rolled resolver that wouldn't honour ``+``/``parents``).

For each product we load the data-lineage DAG from ``manifest.json`` (``graph.py``), restrict the
membership to data nodes, and classify every member as a system-boundary node — inbound / outbound /
both — or, when no lineage crosses the product boundary at that node, internal. See ``graph.py`` for
the exact rule.

The classification is descriptive today; it is the intended input to a future gate that asserts the
right tests / data contracts exist on each boundary node according to its class (inbound nodes need an
ingestion contract, outbound nodes a published contract, etc.).

Boundary analysis is read-only and never gates, so its report's ``ok`` is always True — it reuses the
shared Report renderer purely for the ``--json`` / coloured-stderr / ``--show-passes`` plumbing.
"""

# Standard Library
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

# Third Party
import yaml

# Local
from adaf import config, style, viewer
from adaf.formatting import render_from_args
from adaf.graph import Graph, classify_boundary
from adaf.taxonomy import NodeFacts, load_node_facts

log = logging.getLogger(__name__)

INFO = logging.INFO
ERROR = logging.ERROR

# Display/sort order for the four classifications: boundary roles first (most interesting), interior
# last. Also the canonical key order in the JSON ``counts`` block.
CLASS_ORDER = ["inbound", "outbound", "both", "internal"]


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
    """unique_ids dbt resolves for the named selector — full grammar, via ``dbt ls``.

    ``--quiet`` suppresses dbt's banner; ``--output json`` emits one object per node, from which we
    keep ``unique_id``. We guard on ``startswith("{")`` so any stray non-JSON line is ignored. Fail
    loud if dbt errors (mirrors ``selection.dbt_ls_paths``).
    """
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


# ─── Report ──────────────────────────────────────────────────────────────────


@dataclass
class MemberRow:
    """One classified node within a data product."""

    unique_id: str
    name: str
    resource_type: str
    classification: str  # inbound | outbound | both | internal
    external_parents: list[str]
    external_children: list[str]

    @property
    def is_boundary(self) -> bool:
        return self.classification != "internal"


@dataclass
class ProductBoundary:
    """A data product (named selector) with each of its data nodes classified."""

    product: str
    description: str
    rows: list[MemberRow]

    @property
    def counts(self) -> dict[str, int]:
        counts = {k: 0 for k in CLASS_ORDER}
        for row in self.rows:
            counts[row.classification] += 1
        return counts


@dataclass
class BoundaryReport:
    name: ClassVar[str] = "boundaries"
    products: list[ProductBoundary]
    scope: str

    @property
    def ok(self) -> bool:
        # Descriptive analysis — there is no gate yet, so it always "passes" (exit 0).
        return True

    def summary(self) -> str:
        if not self.products:
            return "no data products defined"
        boundary = sum(c for p in self.products for k, c in p.counts.items() if k != "internal")
        nodes = sum(len(p.rows) for p in self.products)
        return f"{boundary}/{nodes} boundary node(s) across {len(self.products)} data product(s)"

    def to_dict(self) -> dict:
        return {
            "analysis": self.name,
            "ok": self.ok,
            "scope": self.scope,
            "products": [
                {
                    "product": p.product,
                    "description": p.description,
                    "n_members": len(p.rows),
                    "counts": p.counts,
                    "nodes": [
                        {
                            "unique_id": r.unique_id,
                            "name": r.name,
                            "resource_type": r.resource_type,
                            "classification": r.classification,
                            "external_parents": r.external_parents,
                            "external_children": r.external_children,
                        }
                        for r in sorted(p.rows, key=_row_sort_key)
                    ],
                }
                for p in self.products
            ],
        }

    def human_lines(self, *, show_passes: bool = False) -> list[tuple[int, str]]:
        label = style.section("boundaries")
        if not self.products:
            return [(INFO, f"{label}  {style.dim('— no data products defined in selectors.yml')}")]
        lines: list[tuple[int, str]] = [
            (
                INFO,
                f"{label}  {style.bold(f'{len(self.products)} data product(s)')} "
                f"{style.dim('— system-boundary classification')}",
            )
        ]
        for p in self.products:
            counts = p.counts
            breakdown = ", ".join(f"{counts[k]} {k}" for k in CLASS_ORDER if counts[k])
            lines.append(
                (INFO, f"   {style.bold(style.cyan(p.product))} {style.dim(f'({len(p.rows)} node(s): {breakdown})')}")
            )
            shown = p.rows if show_passes else [r for r in p.rows if r.is_boundary]
            for r in sorted(shown, key=_row_sort_key):
                lines.append((INFO, style.boundary_item(r.classification, f"{r.name} ({r.resource_type}){_detail(r)}")))
            hidden = counts["internal"]
            if not show_passes and hidden:
                note = f"· {hidden} internal node(s) hidden — --show-passes to show"
                lines.append((INFO, f"      {style.dim(note)}"))
        return lines


def _row_sort_key(row: MemberRow) -> tuple[int, str]:
    """Boundary roles first (in CLASS_ORDER), then alphabetical by name."""
    return (CLASS_ORDER.index(row.classification), row.name)


def _detail(row: MemberRow) -> str:
    """A concise `← N ext parent(s) → M ext child(ren)` suffix, dimmed; empty for a clean root/leaf."""
    bits: list[str] = []
    if row.external_parents:
        bits.append(f"← {len(row.external_parents)} ext parent(s)")
    if row.external_children:
        bits.append(f"→ {len(row.external_children)} ext child(ren)")
    return f"  {style.dim(' '.join(bits))}" if bits else ""


# ─── Evaluation + handler ────────────────────────────────────────────────────


def evaluate(graph: Graph, named_selectors: list[tuple[str, str]]) -> BoundaryReport:
    """Resolve each named selector to its members and classify them against the graph.

    The membership from dbt is intersected with the graph's data nodes, so tests / semantic models /
    metrics pulled in by ``+`` are dropped (they are attachments, not data lineage — see graph.py).
    """
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
    """Load the graph + the named selectors, narrowed to ``--product`` if given.

    Shared by ``products boundaries`` (descriptive) and ``check system-boundaries`` (gating) — both
    operate over the same data-product selection axis.
    """
    graph = load_graph(args.manifest, parse=getattr(args, "parse", False))
    named_selectors = _filter_named(load_selector_names(args.selectors), list(args.product or []), args.selectors)
    return graph, named_selectors


def cmd(args) -> int:
    graph, named_selectors = _select_named(args)
    return render_from_args(evaluate(graph, named_selectors), args)


# ─── check system-boundaries: gate untested boundary nodes ───────────────────
#
# Promotes the descriptive boundary analysis into a CI gate: every node ON a data product's system
# boundary (inbound / outbound / both) MUST carry at least one test — that test is the enforceable
# half of the data contract at the product's edge. Internal nodes are NOT gated (they are interior to
# the product; their correctness is the producing models' own concern). A node shared by two products
# is evaluated under each, so an untested shared boundary is flagged for every product it endangers.


# Per-class artifact requirements at a product's system boundary, beyond the ≥1-test baseline.
# Maps the catalogue's boundary_class intent to enforceable artifacts (TM-AU-01 / MD-02 + exposure):
#   inbound source  → a freshness SLA (you don't own it; prove it's arriving on time)
#   outbound model  → an enforced contract AND an exposure (a published edge must declare its shape
#                     and name its consumer)
# A `both`-class node owes the union. Inbound models and outbound sources have no extra artifact.
def required_artifacts(classification: str, resource_type: str) -> list[str]:
    req: list[str] = []
    if classification in ("inbound", "both") and resource_type == "source":
        req.append("freshness")
    if classification in ("outbound", "both") and resource_type == "model":
        req += ["contract", "exposure"]
    return req


@dataclass
class BoundaryTestRow:
    """One boundary node of a data product: its test count, plus the per-class artifacts it owes."""

    product: str
    unique_id: str
    name: str
    resource_type: str
    classification: str  # inbound | outbound | both (internal nodes are not gated, so never here)
    test_count: int
    required: list[str] = field(default_factory=list)  # artifacts this boundary class owes
    missing: list[str] = field(default_factory=list)  # required artifacts that are absent

    @property
    def ok(self) -> bool:
        return self.test_count > 0 and not self.missing

    @property
    def present(self) -> list[str]:
        return [a for a in self.required if a not in self.missing]


@dataclass
class SystemBoundaryReport:
    name: ClassVar[str] = "system-boundaries"
    scope: str
    rows: list[BoundaryTestRow]
    error: str | None = None  # set when membership couldn't be resolved (check-all keeps running)

    @property
    def ok(self) -> bool:
        return self.error is None and all(r.ok for r in self.rows)

    def summary(self) -> str:
        if self.error:
            return "could not resolve data products"
        if not self.rows:
            return "no boundary nodes"
        bad = sum(1 for r in self.rows if not r.ok)
        return f"all {len(self.rows)} boundary node(s) satisfied" if self.ok else f"{bad} boundary node(s) under-protected"

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "scope": self.scope,
            "error": self.error,
            "results": [vars(r) | {"ok": r.ok} for r in sorted(self.rows, key=_test_row_sort_key)],
        }

    def human_lines(self, *, show_passes: bool = False) -> list[tuple[int, str]]:
        label = style.section("system-boundaries")
        if self.error:
            return [(ERROR, f"{label}  {style.failed(self.error)}")]
        if not self.rows:
            return [(INFO, f"{label}  {style.dim('— no boundary nodes to gate')}")]
        if self.ok:
            lines: list[tuple[int, str]] = [
                (INFO, f"{label}  {style.passed(f'all {len(self.rows)} boundary node(s) satisfied')}")
            ]
        else:
            bad = sum(1 for r in self.rows if not r.ok)
            lines = [(ERROR, f"{label}  {style.failed(f'{bad} boundary node(s) under-protected')}")]
        # Group rows by product so each product's at-risk edge is clear.
        shown = self.rows if show_passes else [r for r in self.rows if not r.ok]
        for product in dict.fromkeys(r.product for r in self.rows):  # stable, definition order
            product_rows = [r for r in shown if r.product == product]
            if not product_rows:
                continue
            lines.append((INFO, f"   {style.bold(style.cyan(product))}"))
            for r in sorted(product_rows, key=_test_row_sort_key):
                desc = f"{r.name} ({r.resource_type}, {r.classification})"
                req = f" · needs: {', '.join(r.required)}" if r.required else ""
                if r.ok:
                    lines.append((INFO, style.pass_item(f"{desc} — {r.test_count} test(s){req}")))
                else:
                    gaps = []
                    if r.test_count == 0:
                        gaps.append("no tests")
                    if r.missing:
                        gaps.append("missing " + ", ".join(r.missing))
                    lines.append((ERROR, style.fail_item(f"{desc} — {'; '.join(gaps)}{req}")))
        return lines


def _test_row_sort_key(row: BoundaryTestRow) -> tuple[str, int, str]:
    """Group by product, then boundary role (CLASS_ORDER), then name."""
    return (row.product, CLASS_ORDER.index(row.classification), row.name)


def load_exposure_targets(manifest_path: Path | str) -> set[str]:
    """unique_ids of every node referenced by an ``exposures:`` block (its ``depends_on.nodes``).

    A node is "published" — i.e. has a declared downstream consumer — iff it appears here.
    """
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    targets: set[str] = set()
    for exp in (data.get("exposures") or {}).values():
        targets.update((exp.get("depends_on") or {}).get("nodes", []))
    return targets


def _missing_artifacts(uid: str, classification: str, resource_type: str,
                       facts: dict[str, NodeFacts] | None, exposures: set[str] | None) -> tuple[list[str], list[str]]:
    """(required, missing) artifacts for a boundary node. With no facts/exposures, nothing is required
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
    return required, missing


def evaluate_system_boundaries(
    graph: Graph,
    named_selectors: list[tuple[str, str]],
    *,
    node_facts: dict[str, NodeFacts] | None = None,
    exposure_targets: set[str] | None = None,
) -> SystemBoundaryReport:
    """Classify each product's nodes; emit a row per BOUNDARY node with its test count and the
    per-class artifacts it owes (freshness / contract / exposure). When ``node_facts`` is omitted the
    gate degrades to the legacy ≥1-test check (used by the existing unit tests)."""
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
            required, missing = _missing_artifacts(uid, nb.classification, resource_type, node_facts, exposure_targets)
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
                )
            )
    scope = f"system boundaries of {len(named_selectors)} data product(s)"
    return SystemBoundaryReport(scope, rows)


def cmd_check(args) -> int:
    graph, named_selectors = _select_named(args)
    facts = {n.unique_id: n for n in load_node_facts(args.manifest)}
    exposures = load_exposure_targets(args.manifest)
    return render_from_args(
        evaluate_system_boundaries(graph, named_selectors, node_facts=facts, exposure_targets=exposures), args
    )


# ─── products generate / serve: the interactive sdag viewer ──────────────────
#
# The visualisation half: render the full lineage with the data products overlaid as compound boxes
# (full graph) and as collapsed super-nodes (super graph), then serve the static bundle. Membership
# uses the RAW resolve_members (no data-node intersection) so the viewer shows tests / sources /
# semantic models too; the heavy lifting lives in viewer.py.


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
