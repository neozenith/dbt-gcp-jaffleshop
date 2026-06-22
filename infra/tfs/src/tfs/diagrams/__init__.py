"""Diagram generation for `tfs diagram`.

Renders a cloud architecture diagram from a Terraform plan as a draw.io-compatible
SVG (an SVG carrying the editable mxGraph model in its ``content`` attribute) plus
a rasterized PNG. Icons come from vendored draw.io stencils (``assets/stencils.json``,
keyed per provider via :mod:`tfs.diagrams.registry`) — no external diagramming
package or system ``dot`` binary required.
"""
