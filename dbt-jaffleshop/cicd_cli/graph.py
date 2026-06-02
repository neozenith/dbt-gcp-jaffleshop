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

Pure: ``Graph`` and ``classify_boundary`` take plain data and read no I/O beyond ``Graph.load``'s
single file read, so the classification is unit-testable against a hand-built manifest dict.
"""

# Standard Library
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# The resource types that carry data and so form the lineage backbone. Everything else in the
# manifest (test, semantic_model, metric, exposure, analysis, ...) is an attachment/consumer and is
# excluded from both the node set and the edge set.
DATA_RESOURCE_TYPES = frozenset({"model", "source", "seed", "snapshot"})


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
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, data: dict) -> "Graph":
        # Pass 1: the data nodes (model/source/seed/snapshot), without test counts yet.
        raw: dict[str, tuple[str, str]] = {}  # uid -> (resource_type, name)
        for section in ("nodes", "sources"):
            for uid, node in (data.get(section) or {}).items():
                rt = node.get("resource_type") or ("source" if section == "sources" else "")
                if rt not in DATA_RESOURCE_TYPES:
                    continue
                raw[uid] = (rt, node.get("name") or uid.rsplit(".", 1)[-1])
        # Pass 2: attribute each test node to the data node(s) its `depends_on.nodes` references — a
        # model can be referenced by many tests, and sources/seeds/snapshots carry tests too (same
        # approach as manifest.py, but for every data node, not just models).
        test_counts: dict[str, int] = defaultdict(int)
        for node in (data.get("nodes") or {}).values():
            if node.get("resource_type") != "test":
                continue
            for dep in (node.get("depends_on") or {}).get("nodes", []):
                if dep in raw:
                    test_counts[dep] += 1
        nodes = {uid: NodeInfo(uid, rt, name, test_counts.get(uid, 0)) for uid, (rt, name) in raw.items()}
        # parent_map is keyed by child → [parents]; keep only edges where BOTH ends are data nodes.
        parent_map = data.get("parent_map") or {}
        edges = [
            (parent, child)
            for child, parents in parent_map.items()
            for parent in (parents or [])
            if parent in nodes and child in nodes
        ]
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
