"""Render the graph as a draw.io-compatible SVG.

The visible vector is drawn from the vendored stencils (icons), cluster boxes,
edges and labels. The root ``<svg>`` also carries the editable mxGraph model in
its ``content`` attribute (:mod:`tfs.diagrams.drawio_model`), so the very same
file opens as an editable diagram in draw.io. Icons are tinted by replacing the
stencil's ``currentColor`` placeholder with the resolved category colour — no
dependency on the renderer honouring ``currentColor``.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from tfs.diagrams import drawio_model, registry, stencils
from tfs.diagrams.layout import ICON, Box, Layout
from tfs.diagrams.plan_model import ACTION_STYLE, Graph, Node, short_type

_CLUSTER_FILL = "#f8fafc"
_LABEL = "#1e293b"
_SUBLABEL = "#64748b"


def _icon_svg(node: Node, box: Box, color: str) -> str:
    stencil = stencils.get(node.stencil_id)
    cx = box.x + box.w / 2
    top = box.y + 12
    if stencil is None:
        # No icon: a small rounded chip in the category colour.
        return (
            f'<rect x="{cx - ICON / 2:.1f}" y="{top:.1f}" width="{ICON:.1f}" height="{ICON:.1f}" '
            f'rx="8" fill="#ffffff" stroke="{color}" stroke-width="2"/>'
        )
    scale = ICON / max(stencil.w, stencil.h)
    tx = cx - stencil.w * scale / 2
    ty = top + (ICON - stencil.h * scale) / 2
    frag = stencil.svg.replace("currentColor", color)
    return f'<g transform="translate({tx:.2f} {ty:.2f}) scale({scale:.4f})">{frag}</g>'


def _node_svg(node: Node, box: Box, mode: str) -> str:
    color = registry.color_for(node.tf_type)
    border, glyph = color, ""
    if mode == "plan":
        g, c = node.action_style()
        border, glyph = c, (f"{g} " if g else "")

    name = escape(f"{glyph}{node.display_name}")
    sub = escape(short_type(node.tf_type))
    cx = box.x + box.w / 2
    text_y = box.y + 12 + ICON + 18
    return (
        f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
        f'rx="10" fill="#ffffff" stroke="{border}" stroke-width="2"/>'
        f"{_icon_svg(node, box, color)}"
        f'<text x="{cx:.1f}" y="{text_y:.1f}" text-anchor="middle" font-family="sans-serif" '
        f'font-size="13" font-weight="600" fill="{_LABEL}">{name}</text>'
        f'<text x="{cx:.1f}" y="{text_y + 16:.1f}" text-anchor="middle" font-family="sans-serif" '
        f'font-size="10" fill="{_SUBLABEL}">{sub}</text>'
    )


def _cluster_svg(label: str, box: Box) -> str:
    color = registry.CATEGORY_COLOR.get(label, registry.CATEGORY_COLOR["Other"])
    return (
        f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
        f'rx="12" fill="{_CLUSTER_FILL}" stroke="{color}" stroke-width="1.5" opacity="0.95"/>'
        f'<text x="{box.x + 14:.1f}" y="{box.y + 20:.1f}" font-family="sans-serif" font-size="13" '
        f'font-weight="700" fill="{color}">{escape(label)}</text>'
    )


def _edge_svg(src: Box, dst: Box, label: str, dashed: bool) -> str:
    stroke = "#9aa5b1" if dashed else "#94a3b8"
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    line = (
        f'<line x1="{src.cx:.1f}" y1="{src.cy:.1f}" x2="{dst.cx:.1f}" y2="{dst.cy:.1f}" '
        f'stroke="{stroke}" stroke-width="1.5"{dash} marker-end="url(#arrow)"/>'
    )
    if not label:
        return line
    mx, my = (src.cx + dst.cx) / 2, (src.cy + dst.cy) / 2
    return (
        line + f'<text x="{mx:.1f}" y="{my - 3:.1f}" text-anchor="middle" font-family="sans-serif" '
        f'font-size="9" fill="{_SUBLABEL}">{escape(label)}</text>'
    )


def _legend_svg(layout: Layout) -> str:
    items = [("create", "+"), ("update", "~"), ("replace", "±"), ("delete", "-")]
    colors = {
        "create": ACTION_STYLE[("create",)][1],
        "update": ACTION_STYLE[("update",)][1],
        "replace": ACTION_STYLE[("create", "delete")][1],
        "delete": ACTION_STYLE[("delete",)][1],
    }
    x, y = 28.0, layout.height - 22.0
    parts = [
        f'<text x="{x:.0f}" y="{y - 14:.0f}" font-family="sans-serif" font-size="10" '
        f'font-weight="700" fill="{_SUBLABEL}">plan</text>'
    ]
    for label, glyph in items:
        parts.append(
            f'<text x="{x:.0f}" y="{y:.0f}" font-family="sans-serif" font-size="11" '
            f'fill="{colors[label]}">{glyph} {label}</text>'
        )
        x += 78
    return "".join(parts)


def render(graph: Graph, layout: Layout, *, title: str, mode: str) -> str:
    mxfile = drawio_model.build_mxfile(graph, layout, title=title)
    legend_h = 40 if mode == "plan" else 0
    w, h = layout.width, layout.height + legend_h

    body = [
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="#94a3b8"/></marker></defs>',
        f'<rect width="{w:.1f}" height="{h:.1f}" fill="#ffffff"/>',
        f'<text x="{layout.width / 2:.1f}" y="20" text-anchor="middle" font-family="sans-serif" '
        f'font-size="15" font-weight="700" fill="{_LABEL}">{escape(title)}</text>',
    ]
    body += [_cluster_svg(cat, box) for cat, box in sorted(layout.clusters.items())]
    for edge in graph.edges:
        if edge.src in layout.nodes and edge.dst in layout.nodes:
            body.append(_edge_svg(layout.nodes[edge.src], layout.nodes[edge.dst], edge.label, edge.dashed))
    body += [_node_svg(graph.nodes[nid], box, mode) for nid, box in sorted(layout.nodes.items())]
    if mode == "plan":
        body.append(_legend_svg(layout))

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
        f'viewBox="0 0 {w:.0f} {h:.0f}" content={quoteattr(mxfile)}>{"".join(body)}</svg>\n'
    )
