"""Lineage graph over a dbt manifest — the data-DAG backbone for data-product boundary analysis.

Only the *data-carrying* resource types form the backbone: model, source, seed, snapshot.
Tests, semantic models, metrics, exposures and analyses are attachments *on* or consumers *of*
those nodes, not data lineage themselves — including them would misclassify every tested model as
an "outbound boundary" (its test node is a child) and distort the picture with consumer edges. So
BOTH the node set and the edge set are filtered to data nodes: an edge survives only if both of its
endpoints are data nodes (this is what drops the ``model → test`` / ``model → semantic_model`` edges).

The boundary question this enables: given a named selector's member set Mₛ (a "data product"), which
members sit on the product's system boundary — i.e. have a lineage edge crossing into or out of Mₛ?

    inbound(m)  := m has a parent OUTSIDE Mₛ, OR no parent INSIDE Mₛ   (an entry point)
    outbound(m) := m has a child  OUTSIDE Mₛ, OR no child  INSIDE Mₛ   (an exit point)
    both        := inbound AND outbound
    internal    := neither (fully interior to the product)

The "no internal parent/child" clauses fold in the topological roots/leaves: a true source (no
parents at all) is an inbound boundary because the product's lineage *starts* there; a final mart (no
children at all) is an outbound boundary because the product's lineage *ends* there — exactly the
points where a data contract with the outside world has to live.

Pure: ``Graph`` and ``classify_boundary`` take plain data and read no I/O. The mechanical manifest
parse lives once in :class:`~adaf.dbt.manifest_view.ManifestView`; ``Graph.load`` /
``Graph.from_dict`` are thin wrappers over :meth:`Graph.from_view`, so the classification stays
unit-testable against a hand-built manifest dict.
"""

# Standard Library
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Local
from adaf.dbt.manifest_view import ManifestView

# The resource types that carry data and so form the lineage backbone. Everything else in the
# manifest (test, semantic_model, metric, exposure, analysis, ...) is an attachment/consumer and is
# excluded from both the node set and the edge set.
DATA_RESOURCE_TYPES = frozenset({"model", "source", "seed", "snapshot"})

# The four boundary labels a member can carry (the string values ``classify_boundary`` returns).
# Exposed as named constants so the boundary-obligation lint (``commands.sdaglint``) reads on labels
# rather than string literals. INNER is "internal" — the label for a fully-interior product member.
INBOUND = "inbound"
OUTBOUND = "outbound"
BOTH = "both"
INNER = "internal"


@dataclass(frozen=True)
class NodeInfo:
    """The minimal display facts about one data node, plus how many tests reference it."""

    unique_id: str
    resource_type: str
    name: str
    test_count: int = 0  # number of test nodes depending on this node (models AND sources/seeds/snapshots)


class Graph:
    """The data-node lineage DAG distilled from a dbt manifest (pure data + adjacency).

    Construct via ``Graph.load(path)`` (reads manifest.json) or ``Graph.from_dict(data)`` (for tests,
    with a hand-built manifest dict — same shape dbt writes: ``nodes``/``sources`` maps + ``parent_map``).
    Both delegate to :meth:`from_view` over a :class:`ManifestView`.
    """

    def __init__(self, nodes: dict[str, NodeInfo], edges: list[tuple[str, str]]) -> None:
        self._nodes = nodes
        self._edges = edges
        self._parents: dict[str, list[str]] = defaultdict(list)
        self._children: dict[str, list[str]] = defaultdict(list)
        for parent, child in edges:
            self._parents[child].append(parent)
            self._children[parent].append(child)

    @classmethod
    def load(cls, path: Path | str) -> "Graph":
        return cls.from_view(ManifestView.load(path))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Graph":
        """Build from an already-parsed manifest dict (convenience wrapper over :meth:`from_view`)."""
        return cls.from_view(ManifestView.from_dict(data))

    @classmethod
    def from_view(cls, view: ManifestView) -> "Graph":
        # The data nodes (model/source/seed/snapshot) are the only backbone; test counts come from a
        # second pass over the `test` nodes (same approach as manifest.py, but for every data node).
        data_records = view.of_type(*DATA_RESOURCE_TYPES)
        test_counts: dict[str, int] = defaultdict(int)
        for rec in view.of_type("test").values():
            for dep in (rec.raw.get("depends_on") or {}).get("nodes", []):
                if dep in data_records:
                    test_counts[dep] += 1
        nodes = {
            uid: NodeInfo(uid, rec.resource_type, rec.raw.get("name") or uid.rsplit(".", 1)[-1], test_counts.get(uid, 0))
            for uid, rec in data_records.items()
        }
        # The view keeps only edges whose BOTH endpoints are in the set we pass (drops model->test).
        edges = view.parent_edges(set(nodes))
        return cls(nodes, edges)

    def nodes(self) -> dict[str, NodeInfo]:
        return self._nodes

    def edges(self) -> list[tuple[str, str]]:
        return self._edges

    def info(self, uid: str) -> NodeInfo | None:
        return self._nodes.get(uid)

    def parents_of(self, uid: str) -> list[str]:
        return self._parents.get(uid, [])

    def children_of(self, uid: str) -> list[str]:
        return self._children.get(uid, [])

    def classify(self, members: set[str]) -> dict[str, str]:
        """Classify each member as an ``inbound`` / ``outbound`` / ``both`` / ``internal`` boundary
        node — the string-label convenience over :func:`classify_boundary` the boundary-obligation
        lint (``commands.sdaglint``) consumes. Non-data members (e.g. a ``test`` that slipped into the
        selector) carry no node in this graph, so :func:`classify_boundary` still labels them by their
        edges; callers that only care about data members intersect with :meth:`nodes` themselves.
        """
        return {uid: nb.classification for uid, nb in classify_boundary(members, self._edges).items()}


# ─── Boundary classification (pure) ──────────────────────────────────────────


@dataclass(frozen=True)
class NodeBoundary:
    """One member's role in a data product's system boundary."""

    unique_id: str
    classification: str  # "inbound" | "outbound" | "both" | "internal"
    external_parents: list[str]  # parent unique_ids OUTSIDE the product (data the product consumes)
    external_children: list[str]  # child unique_ids OUTSIDE the product (consumers of the product)

    @property
    def is_boundary(self) -> bool:
        return self.classification != "internal"


def classify_boundary(
    members: Iterable[str],
    edges: Iterable[tuple[str, str]],
) -> dict[str, NodeBoundary]:
    """Classify each member as an inbound / outbound / both / internal system-boundary node.

    Args:
        members: unique_ids forming the data product (a selector's data-node members).
        edges:   the FULL data-lineage edge list — NOT scoped to ``members``; the boundary test
                 needs to see edges that reach nodes OUTSIDE the product.

    Returns:
        ``{unique_id: NodeBoundary}`` for every member.
    """
    members = set(members)
    parents_of: dict[str, list[str]] = defaultdict(list)
    children_of: dict[str, list[str]] = defaultdict(list)
    for parent, child in edges:
        parents_of[child].append(parent)
        children_of[parent].append(child)

    result: dict[str, NodeBoundary] = {}
    for uid in members:
        parents = parents_of.get(uid, [])
        children = children_of.get(uid, [])
        internal_parents = [p for p in parents if p in members]
        internal_children = [c for c in children if c in members]
        external_parents = sorted(p for p in parents if p not in members)
        external_children = sorted(c for c in children if c not in members)
        # Entry point: a parent outside the product, OR no parent inside it (a topological root).
        inbound = bool(external_parents) or not internal_parents
        # Exit point: a child outside the product, OR no child inside it (a topological leaf).
        outbound = bool(external_children) or not internal_children
        classification = (
            "both" if inbound and outbound else "inbound" if inbound else "outbound" if outbound else "internal"
        )
        result[uid] = NodeBoundary(uid, classification, external_parents, external_children)
    return result
