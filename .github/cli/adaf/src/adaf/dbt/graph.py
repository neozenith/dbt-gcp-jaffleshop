"""Lineage graph over a dbt manifest — the data-DAG backbone for data-product boundary analysis.

The graph's nodes are the *data-carrying* types (``model``, ``source``, ``seed``, ``snapshot``)
**plus ``exposure``** — exposures are downstream consumers that a model can ref, and a model feeding
an exposure outside the product is an outbound boundary, so the exposure edge has to exist. Tests,
semantic models, metrics and analyses are still excluded (a childless ``test`` would read as an
outbound leaf, and a model whose only child is a test would be pushed outbound by that edge).

The boundary question: given a named selector's member set (a "data product"), where does each
**model** sit relative to the product's *system boundary*? Only the product's MODELS are classified
(the nodes carrying contractual obligations); sources and exposures are NOT labelled — they exist
only as the *edges* that cross the boundary. The "product interior" is therefore the set of MODEL
members, and a parent/child outside it (a source, an exposure, or a model in another product) is
"external":

    inbound(m)  = m has a parent outside the model interior, OR no parent inside it  (an entry point)
    outbound(m) = m has a child  outside the model interior, OR no child  inside it  (an exit point)
    both        = inbound and outbound
    inner       = neither (fully interior to the product)

The "no internal parent/child" clauses fold in the topological roots/leaves: a staging model reading
only a source is an inbound boundary (its lineage *starts* outside); a final mart with no in-product
child is an outbound boundary (its lineage *ends* outside) — exactly where a contract with the
outside world has to live.

The DAG itself is a ``networkx.DiGraph`` (mature graph primitives — predecessors/successors and
traversals — rather than a hand-rolled adjacency map; see AGENTS.md ADR-0002). ``Graph`` and
``Graph.classify`` operate on plain manifest data and read no I/O beyond ``load_graph``'s single
file read, so the classification is unit-testable against a hand-built manifest dict. No dbt or git
subprocess is invoked.
"""

# Standard Library
from pathlib import Path
from typing import Any

# Third Party
import networkx as nx

# Local
from adaf.dbt.manifest_view import ManifestView

# The resource types that carry data and so form the lineage backbone. Everything else in the
# manifest (test, semantic_model, metric, analysis, …) is an attachment and is excluded from both
# the node set and the edge set. NOTE: ``exposure`` is NOT in this set (it is not data lineage) but
# IS added to the boundary graph separately (see :meth:`Graph.from_view`) as a downstream consumer.
DATA_RESOURCE_TYPES = frozenset({"model", "source", "seed", "snapshot"})

# Only MODELS carry a boundary role (they own the contractual obligations); sources/exposures appear
# in the graph only as the edges that cross the product boundary.
SUBJECT_RESOURCE_TYPE = "model"

# The four boundary labels a member can carry.
INBOUND = "inbound"
OUTBOUND = "outbound"
BOTH = "both"
INNER = "inner"


class Graph:
    """The lineage DAG distilled from a dbt manifest, held as a ``networkx.DiGraph``.

    Construct via ``load_graph(path)`` (reads manifest.json) or ``Graph.from_dict(data)`` (for tests,
    with a hand-built manifest dict — same shape dbt writes: a ``parent_map`` of child -> [parents],
    falling back to each node's ``depends_on.nodes`` when no ``parent_map`` is present). Edges point
    parent -> child, so a node's parents are its predecessors and its children its successors.
    """

    def __init__(self, nodes: set[str], edges: list[tuple[str, str]], types: dict[str, str] | None = None) -> None:
        self._g: nx.DiGraph = nx.DiGraph()
        self._g.add_nodes_from(nodes)
        self._g.add_edges_from(edges)
        # uid -> resource_type, so classify() can restrict its subjects + interior to models.
        self._types: dict[str, str] = dict(types or {})

    @classmethod
    def from_view(cls, view: ManifestView) -> "Graph":
        # Backbone = the data nodes (model/source/seed/snapshot) PLUS exposures (downstream consumers
        # a model can ref). Tests / semantic models / metrics / analyses stay excluded. The view keeps
        # only edges whose BOTH endpoints are present, so model->exposure survives but model->test does not.
        data_nodes = set(view.of_type(*DATA_RESOURCE_TYPES))
        exposures = set(view.section("exposures"))
        present = data_nodes | exposures
        types: dict[str, str] = {uid: rec.resource_type for uid, rec in view.records().items() if uid in data_nodes}
        types.update(dict.fromkeys(exposures, "exposure"))
        return cls(present, view.parent_edges(present), types)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Graph":
        """Build from an already-parsed manifest dict (convenience wrapper over :meth:`from_view`)."""
        return cls.from_view(ManifestView.from_dict(data))

    def nodes(self) -> set[str]:
        return set(self._g.nodes)

    def edges(self) -> list[tuple[str, str]]:
        return list(self._g.edges)

    def parents_of(self, uid: str) -> list[str]:
        return list(self._g.predecessors(uid)) if self._g.has_node(uid) else []

    def children_of(self, uid: str) -> list[str]:
        return list(self._g.successors(uid)) if self._g.has_node(uid) else []

    def attribute(self, members: set[str]) -> dict[str, dict[str, Any]]:
        """Like :meth:`classify`, but each MODEL also carries an **attribution** — the specific reasons
        it got its label, for debugging / triaging the boundary algorithm.

        Returns ``{unique_id: {"boundary": label, "attribution": [reason, ...]}}`` for every MODEL
        member. Each reason is ``{"axis", "code", "nodes", "message"}``:

        * ``axis`` — ``inbound`` / ``outbound`` / ``inner`` (which side of the boundary the reason supports);
        * ``code`` — one of ``external_parent`` / ``topological_root`` / ``external_child`` /
          ``topological_leaf`` / ``interior``;
        * ``nodes`` — the specific crossing ``unique_id``s (a source, an exposure, a model in another product);
        * ``message`` — a one-line human explanation.

        So a node labelled ``outbound`` with ``[{code: external_child, nodes: ['exposure.x.dash']}]`` tells
        you EXACTLY which edge pushed it out — the attribution is the audit trail behind the label.
        """
        interior = {uid for uid in members if self._types.get(uid) == SUBJECT_RESOURCE_TYPE}
        out: dict[str, dict[str, Any]] = {}
        for uid in interior:
            if not self._g.has_node(uid):
                continue
            parents = list(self._g.predecessors(uid))
            children = list(self._g.successors(uid))
            ext_parents = sorted(p for p in parents if p not in interior)
            ext_children = sorted(c for c in children if c not in interior)
            internal_parent = any(p in interior for p in parents)
            internal_child = any(c in interior for c in children)

            attribution: list[dict[str, Any]] = []
            if ext_parents:
                attribution.append(
                    {
                        "axis": INBOUND,
                        "code": "external_parent",
                        "nodes": ext_parents,
                        "message": f"reads {len(ext_parents)} ref(s) from outside the product",
                    }
                )
            if not internal_parent:
                attribution.append(
                    {
                        "axis": INBOUND,
                        "code": "topological_root",
                        "nodes": [],
                        "message": "no in-product model feeds this node (entry point)",
                    }
                )
            if ext_children:
                attribution.append(
                    {
                        "axis": OUTBOUND,
                        "code": "external_child",
                        "nodes": ext_children,
                        "message": f"feeds {len(ext_children)} ref(s) outside the product",
                    }
                )
            if not internal_child:
                attribution.append(
                    {
                        "axis": OUTBOUND,
                        "code": "topological_leaf",
                        "nodes": [],
                        "message": "no in-product model consumes this node (exit point)",
                    }
                )

            inbound = bool(ext_parents) or not internal_parent
            outbound = bool(ext_children) or not internal_child
            label = BOTH if (inbound and outbound) else INBOUND if inbound else OUTBOUND if outbound else INNER
            if label == INNER:
                attribution.append(
                    {
                        "axis": INNER,
                        "code": "interior",
                        "nodes": [],
                        "message": "all refs are in-product (no boundary-crossing edge)",
                    }
                )
            out[uid] = {"boundary": label, "attribution": attribution}
        return out

    def classify(self, members: set[str]) -> dict[str, str]:
        """Classify each MODEL member as an inbound / outbound / both / inner boundary node.

        Only the product's **models** are classified — they own the boundary obligations. The product
        *interior* is that same set of model members; a parent or child OUTSIDE it (a source, an
        exposure, or a model in another product) is "external". So a member is an **entry point**
        (``inbound``) when it has an external parent OR no model parent inside the product (a staging
        model reading a source); an **exit point** (``outbound``) when it has an external child OR no
        model child inside it (a mart whose only consumer is an exposure, or a leaf). ``both`` is the
        union; ``inner`` is a model fully interior to the product.

        Sources, exposures, seeds, snapshots and tests in ``members`` are NOT returned — they are
        either edge context (sources/exposures) or excluded entirely (tests).

        Args:
            members: the unique_ids forming the data product (a selector's member set).

        Returns:
            ``{unique_id: "inbound" | "outbound" | "both" | "inner"}`` for every MODEL member. Use
            :meth:`attribute` to also get WHY each node got its label.
        """
        return {uid: info["boundary"] for uid, info in self.attribute(members).items()}


def load_graph(manifest_path: Path) -> Graph:
    """Load the lineage ``Graph`` from a dbt ``manifest.json`` on disk (reads via ``ManifestView``)."""
    return Graph.from_view(ManifestView.load(manifest_path))
