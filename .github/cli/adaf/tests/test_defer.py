"""Tests for ``adaf.commands.defer`` pure helpers.

``cmd_defer_diff`` shells out to dbt + needs a built ``--state`` baseline, so it isn't driven
here (the project forbids mocks). The git-diff-style facet renderer used by ``--details`` is a
pure function over two manifest nodes, so it is unit-tested directly.
"""

# Local
from adaf.commands.defer import _facet_diff_lines, _why_modified


def test_why_modified_lists_changed_facets() -> None:
    base = {"checksum": {"checksum": "aaa"}, "config": {"materialized": "view"}, "columns": {}, "depends_on": {}}
    cur = {"checksum": {"checksum": "bbb"}, "config": {"materialized": "table"}, "columns": {}, "depends_on": {}}
    assert _why_modified(base, cur) == ["checksum", "config"]


def test_facet_diff_lines_git_style_plain() -> None:
    base = {"config": {"materialized": "view"}}
    cur = {"config": {"materialized": "table"}}
    lines = _facet_diff_lines(base, cur, color=False)
    text = "\n".join(lines)
    # Unified-diff hunk header for the changed facet, plus a -/+ pair for the changed value.
    assert "config @baseline" in text
    assert "config @current" in text
    assert any(ln.startswith("-") and "view" in ln for ln in lines)
    assert any(ln.startswith("+") and "table" in ln for ln in lines)


def test_facet_diff_lines_colourises_add_remove() -> None:
    base = {"columns": {"a": {"name": "a"}}}
    cur = {"columns": {"a": {"name": "a"}, "b": {"name": "b"}}}
    lines = _facet_diff_lines(base, cur, color=True)
    joined = "\n".join(lines)
    assert "\x1b[32m" in joined  # an added (+) line in green
    assert "\x1b[36m" in joined  # the @@ hunk header in cyan


def test_facet_diff_lines_empty_when_unchanged() -> None:
    node = {"checksum": {"checksum": "x"}, "config": {}, "columns": {}, "depends_on": {}}
    assert _facet_diff_lines(node, dict(node), color=False) == []
