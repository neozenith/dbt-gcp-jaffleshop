"""Deterministic geometry for the graph: cluster-by-category columns, nodes
gridded within each cluster. Pure (no rendering), so layout is unit-testable.

Coordinates are in SVG user units, origin top-left. The layout is intentionally
simple — clusters left-to-right, nodes stacked top-down and wrapped into extra
in-cluster columns past ``MAX_ROWS`` — which is plenty for stack-sized diagrams
and keeps the output stable for golden tests.
"""

from __future__ import annotations

from dataclasses import dataclass

from tfs.diagrams.plan_model import Graph

# Visual constants (SVG user units).
NODE_W = 168
NODE_H = 104
ICON = 56
COL_GAP = 56
ROW_GAP = 30
PAD = 22
TITLE_H = 30
MARGIN = 28
MAX_ROWS = 6


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class Layout:
    nodes: dict[str, Box]
    clusters: dict[str, Box]
    width: float
    height: float


def _cluster_order(graph: Graph) -> dict[str, list[str]]:
    """category -> sorted node ids (categories sorted; stable for goldens)."""
    by_cat: dict[str, list[str]] = {}
    for node_id, node in graph.nodes.items():
        by_cat.setdefault(node.category, []).append(node_id)
    return {cat: sorted(by_cat[cat]) for cat in sorted(by_cat)}


def compute(graph: Graph) -> Layout:
    by_cat = _cluster_order(graph)
    nodes: dict[str, Box] = {}
    clusters: dict[str, Box] = {}

    x = MARGIN
    max_bottom = MARGIN
    for cat, ids in by_cat.items():
        rows = min(len(ids), MAX_ROWS)
        cols = (len(ids) + MAX_ROWS - 1) // MAX_ROWS
        cluster_w = PAD * 2 + cols * NODE_W + (cols - 1) * COL_GAP
        cluster_h = TITLE_H + PAD * 2 + rows * NODE_H + (rows - 1) * ROW_GAP
        clusters[cat] = Box(x, MARGIN, cluster_w, cluster_h)

        for i, node_id in enumerate(ids):
            col, row = divmod(i, MAX_ROWS)
            nx = x + PAD + col * (NODE_W + COL_GAP)
            ny = MARGIN + TITLE_H + PAD + row * (NODE_H + ROW_GAP)
            nodes[node_id] = Box(nx, ny, NODE_W, NODE_H)

        max_bottom = max(max_bottom, MARGIN + cluster_h)
        x += cluster_w + COL_GAP

    width = x - COL_GAP + MARGIN if by_cat else MARGIN * 2
    height = max_bottom + MARGIN
    return Layout(nodes=nodes, clusters=clusters, width=width, height=height)
