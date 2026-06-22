"""Terraform plan JSON -> a typed node/edge graph for rendering.

`terraform show -json <plan>` carries three sections we use:

  * .planned_values   -> the full intended resource set      (--mode state)
  * .resource_changes -> the delta + per-resource action      (--mode plan)
  * .configuration    -> the reference graph (edges)          (both modes)

This module is pure (no terraform/IO) so it is fully unit-testable against a
committed fixture. Classification (icon/skip/iam/identity) is delegated to
:mod:`tfs.diagrams.registry` — the cloud-agnostic seam.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from tfs.diagrams import registry

Doc = dict[str, Any]

# Plan action set (sorted tuple) -> (glyph, colour). Mirrors `terraform plan`.
ACTION_STYLE: dict[tuple[str, ...], tuple[str, str]] = {
    ("create",): ("+", "#16a34a"),
    ("update",): ("~", "#d97706"),
    ("delete",): ("-", "#dc2626"),
    ("create", "delete"): ("±", "#7c3aed"),  # replace
    ("no-op",): ("", "#64748b"),
    ("read",): ("", "#64748b"),
}

_INDEX_SUFFIX = re.compile(r"\[.*\]$")


def base_address(address: str) -> str:
    """Strip a for_each/count index: foo.bar["k"] -> foo.bar, foo.bar[0] -> foo.bar."""
    return _INDEX_SUFFIX.sub("", address)


def short_type(tf_type: str) -> str:
    return tf_type.removeprefix("google_")


@dataclass
class Node:
    id: str  # base address, e.g. google_storage_bucket.assets
    tf_type: str
    name: str
    count: int = 0
    actions: tuple[str, ...] = ()
    role: str | None = None

    @property
    def stencil_id(self) -> str | None:
        return registry.stencil_for(self.tf_type)[0]

    @property
    def category(self) -> str:
        return registry.category_for(self.tf_type)

    @property
    def display_name(self) -> str:
        return f"{self.name} x{self.count}" if self.count > 1 else self.name

    def action_style(self) -> tuple[str, str]:
        return ACTION_STYLE.get(tuple(sorted(self.actions)), ("", "#334155"))


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    dashed: bool = False


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)


# --- raw section walkers -------------------------------------------------------


def _iter_planned(doc: Doc) -> Iterator[tuple[str, str, str, Doc, str]]:
    def walk(module: Doc) -> Iterator[tuple[str, str, str, Doc, str]]:
        for res in module.get("resources", []):
            yield res["address"], res["type"], res["name"], res.get("values", {}), res.get("mode", "managed")
        for child in module.get("child_modules", []):
            yield from walk(child)

    yield from walk(doc.get("planned_values", {}).get("root_module", {}))


def _iter_changes(doc: Doc) -> Iterator[tuple[str, str, str, tuple[str, ...], Doc, str]]:
    for rc in doc.get("resource_changes", []):
        change = rc.get("change", {})
        yield (
            rc["address"],
            rc["type"],
            rc["name"],
            tuple(change.get("actions", [])),
            (change.get("after") or {}),
            rc.get("mode", "managed"),
        )


def _collect_references(expr: object) -> list[str]:
    refs: list[str] = []
    if isinstance(expr, dict):
        maybe = expr.get("references")
        if isinstance(maybe, list):
            refs.extend(str(r) for r in maybe)
        for value in expr.values():
            refs.extend(_collect_references(value))
    elif isinstance(expr, list):
        for value in expr:
            refs.extend(_collect_references(value))
    return refs


def _resolve_reference(ref: str, addresses: set[str]) -> str | None:
    """'google_service_account.runtime.email' -> longest managed address it starts with."""
    parts = ref.split(".")
    for n in range(len(parts), 0, -1):
        candidate = ".".join(parts[:n])
        if candidate in addresses:
            return candidate
    return None


def _config_addresses_and_refs(doc: Doc) -> tuple[set[str], list[tuple[str, str]]]:
    resources = doc.get("configuration", {}).get("root_module", {}).get("resources", [])
    addresses = {r["address"] for r in resources}
    pairs = [(r["address"], ref) for r in resources for ref in _collect_references(r.get("expressions", {}))]
    return addresses, pairs


# --- graph assembly ------------------------------------------------------------


def _collect_nodes(doc: Doc, mode: str) -> dict[str, Node]:
    nodes: dict[str, Node] = {}
    if mode == "plan":
        for address, tf_type, name, actions, after, res_mode in _iter_changes(doc):
            if res_mode == "data":
                continue
            n = nodes.setdefault(base_address(address), Node(base_address(address), tf_type, name, actions=actions))
            n.count += 1
            n.role = after.get("role")
    else:
        for address, tf_type, name, values, res_mode in _iter_planned(doc):
            if res_mode == "data":
                continue
            n = nodes.setdefault(base_address(address), Node(base_address(address), tf_type, name))
            n.count += 1
            n.role = values.get("role")
    return nodes


def build_graph(doc: Doc, *, mode: str = "state", iam: str = "edges") -> Graph:
    """Parse a plan JSON document into the renderable Graph (boxes + edges).

    Skipped types are dropped; IAM grants render as dashed role-labelled edges
    (identity -> target) unless ``iam == "nodes"``, in which case they are boxes.
    """
    all_nodes = _collect_nodes(doc, mode)
    addresses, ref_pairs = _config_addresses_and_refs(doc)

    show_iam_as_nodes = iam == "nodes"
    boxes = {
        addr: n
        for addr, n in all_nodes.items()
        if not registry.is_skipped(n.tf_type) and (show_iam_as_nodes or not registry.is_iam_grant(n.tf_type))
    }
    graph = Graph(nodes=boxes)

    # Reference edges between boxes (deduped, no self-loops).
    seen: set[tuple[str, str]] = set()
    for src, ref in ref_pairs:
        src_base = base_address(src)
        dst = _resolve_reference(ref, addresses)
        if dst is None:
            continue
        dst_base = base_address(dst)
        pair = (src_base, dst_base)
        if src_base in boxes and dst_base in boxes and src_base != dst_base and pair not in seen:
            seen.add(pair)
            graph.edges.append(Edge(src_base, dst_base))

    if not show_iam_as_nodes:
        graph.edges.extend(_iam_edges(all_nodes, boxes, addresses, ref_pairs))
    return graph


def _iam_edges(
    all_nodes: dict[str, Node],
    boxes: dict[str, Node],
    addresses: set[str],
    ref_pairs: list[tuple[str, str]],
) -> list[Edge]:
    refs_by_src: dict[str, list[str]] = {}
    for src, ref in ref_pairs:
        refs_by_src.setdefault(base_address(src), []).append(ref)

    edges: list[Edge] = []
    for addr, n in all_nodes.items():
        if not registry.is_iam_grant(n.tf_type):
            continue
        resolved = {
            base_address(t)
            for ref in refs_by_src.get(addr, [])
            if (t := _resolve_reference(ref, addresses)) is not None
        }
        members = [a for a in resolved if a in boxes and registry.is_identity(boxes[a].tf_type)]
        targets = [a for a in resolved if a in boxes and not registry.is_identity(boxes[a].tf_type)]
        role = (n.role or "").removeprefix("roles/")
        for member in sorted(members):
            for target in sorted(targets):
                edges.append(Edge(member, target, label=role, dashed=True))
    return edges
