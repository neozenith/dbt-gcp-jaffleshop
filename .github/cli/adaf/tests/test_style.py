# Local
from adaf import style


def test_disabled_returns_plain_text_but_keeps_emoji():
    style.configure("never")
    assert style.green("hi") == "hi"
    assert style.passed("ok") == "✅ ok"  # emoji stays; no ANSI
    assert style.section("docs") == "📄 docs"


def test_enabled_wraps_with_ansi():
    style.configure("always")
    try:
        out = style.green("hi")
        assert out.startswith("\x1b[32m")
        assert out.endswith("\x1b[0m")
        assert "hi" in out
    finally:
        style.configure("never")  # reset global so other tests see plain text


def test_strip_ansi_removes_escapes():
    assert style.strip_ansi("\x1b[31mred\x1b[0m plain \x1b[1mbold\x1b[0m") == "red plain bold"


def test_every_check_has_a_distinct_emoji():
    names = ["deprecations", "lint", "format", "docs", "tests"]
    emojis = [style.EMOJI[n] for n in names]
    assert all(emojis)  # each present
    assert len(set(emojis)) == len(emojis)  # all distinct
    for name in names:
        assert name in style.section(name)
