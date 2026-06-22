"""Build the editable mxGraph model embedded in the output SVG's ``content``
attribute. Opening the SVG in draw.io restores this model — icons via inline
``shape=stencil(<b64>)`` (self-contained; no stencil library install needed),
geometry matching the rendered SVG.
"""

from __future__ import annotations

from xml.sax.saxutils import quoteattr

from tfs.diagrams import registry, stencils
from tfs.diagrams.layout import Layout
from tfs.diagrams.plan_model import Graph, Node


def _node_style(node: Node) -> str:
    color = registry.color_for(node.tf_type)
    stencil = stencils.get(node.stencil_id)
    if stencil is not None:
        return (
            f"shape=stencil({stencil.stencil_b64});html=1;fillColor={color};strokeColor=none;"
            "verticalLabelPosition=bottom;verticalAlign=top;labelPosition=center;align=center;"
        )
    return f"rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor={color};"


def build_mxfile(graph: Graph, layout: Layout, *, title: str) -> str:
    cell_id: dict[str, str] = {nid: f"n{i}" for i, nid in enumerate(sorted(graph.nodes))}
    cells: list[str] = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']

    for nid, node in sorted(graph.nodes.items()):
        box = layout.nodes[nid]
        cells.append(
            f'<mxCell id="{cell_id[nid]}" value={quoteattr(node.display_name)} '
            f'style={quoteattr(_node_style(node))} vertex="1" parent="1">'
            f'<mxGeometry x="{box.x:.0f}" y="{box.y:.0f}" width="{box.w:.0f}" height="{box.h:.0f}" as="geometry"/>'
            "</mxCell>"
        )

    for i, edge in enumerate(graph.edges):
        if edge.src not in cell_id or edge.dst not in cell_id:
            continue
        style = "endArrow=block;html=1;" + ("dashed=1;strokeColor=#9aa5b1;" if edge.dashed else "strokeColor=#94a3b8;")
        cells.append(
            f'<mxCell id="e{i}" value={quoteattr(edge.label)} style={quoteattr(style)} '
            f'edge="1" parent="1" source="{cell_id[edge.src]}" target="{cell_id[edge.dst]}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )

    model = (
        f'<mxGraphModel dx="{layout.width:.0f}" dy="{layout.height:.0f}" grid="1" gridSize="10" '
        'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" math="0" shadow="0">'
        f"<root>{''.join(cells)}</root></mxGraphModel>"
    )
    return f'<mxfile><diagram name={quoteattr(title)}>{model}</diagram></mxfile>'
