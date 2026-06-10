"""MkDocs build hooks for the guides site.

The testing-taxonomy markdown is authored to render natively on GitHub, so the
cross-references inside Mermaid diagrams are written as relative ``*.md`` links
(e.g. ``href='./entity/README.md'`` on a decision-tree node). MkDocs' markdown
processor rewrites ``.md`` links that appear in *prose*, but it never looks
inside a fenced ```mermaid block — Mermaid renders those client-side from the
raw fence text. Left untouched, clicking a diagram node would resolve to a
``.md`` path that GitHub Pages does not serve (404).

``on_page_markdown`` runs before the markdown is converted to HTML. Here we
rewrite *only* the hrefs that live inside Mermaid fences, resolving each target
through MkDocs' own file table so the emitted link matches whatever URL MkDocs
publishes the page at — and is expressed relative to the current page, so it
works regardless of where the site is mounted (``/guides/`` here).
"""

from __future__ import annotations

import posixpath
import re

from mkdocs.utils import get_relative_url

# Capture each fenced mermaid block (non-greedy, across newlines).
_MERMAID_BLOCK = re.compile(r"```mermaid\n.*?```", re.DOTALL)
# Capture href='...md' / href="...md" inside a block.
_HREF = re.compile(r"""href=(['"])(?P<path>[^'"]+?\.md)\1""")


def on_page_markdown(markdown: str, *, page, config, files):  # noqa: ANN001, ANN201
    """Rewrite relative ``*.md`` hrefs inside Mermaid fences to published URLs."""
    src_dir = posixpath.dirname(page.file.src_uri)

    def _fix_href(hm: re.Match[str]) -> str:
        quote, rel = hm.group(1), hm.group("path")
        # Leave absolute / external links alone.
        if rel.startswith(("http://", "https://", "/", "#")):
            return hm.group(0)
        target = posixpath.normpath(posixpath.join(src_dir, rel))
        dest = files.get_file_from_path(target)
        if dest is None:
            # Target not part of the docs tree — leave it for MkDocs to warn on.
            return hm.group(0)
        new_url = get_relative_url(dest.url, page.file.url)
        return f"href={quote}{new_url}{quote}"

    def _fix_block(bm: re.Match[str]) -> str:
        return _HREF.sub(_fix_href, bm.group(0))

    return _MERMAID_BLOCK.sub(_fix_block, markdown)
