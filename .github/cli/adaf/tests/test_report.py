"""Tests for the shared reporting substrate in ``adaf.report``."""

# Standard Library
import io

# Third Party
import pytest

# Local
from adaf.report import (
    Finding,
    colorize,
    format_location,
    render_file_header,
    render_finding,
    render_findings,
    render_headline,
    render_note,
    should_colorize,
)


class _FakeStream:
    """Stream stub exposing a settable ``isatty`` for colour-resolution tests."""

    def __init__(self, *, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.mark.parametrize(
    "path,line,col,expected",
    [
        ("models/x.sql", None, None, "models/x.sql"),
        ("models/x.sql", 12, None, "models/x.sql:12"),
        ("models/x.sql", 12, 4, "models/x.sql:12:4"),
        ("models/x.sql", None, 4, "models/x.sql"),  # col without line has no anchor
    ],
)
def test_format_location(path: str, line: int | None, col: int | None, expected: str) -> None:
    assert format_location(path, line, col) == expected


def test_should_colorize_always(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")  # always wins even over NO_COLOR
    assert should_colorize("always", _FakeStream(tty=False)) is True


def test_should_colorize_never(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert should_colorize("never", _FakeStream(tty=True)) is False


def test_should_colorize_auto_with_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert should_colorize("auto", _FakeStream(tty=True)) is True


def test_should_colorize_auto_without_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert should_colorize("auto", _FakeStream(tty=False)) is False


def test_should_colorize_no_color_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "")  # any value, including empty string
    assert should_colorize("auto", _FakeStream(tty=True)) is False


def test_colorize_noop_when_disabled() -> None:
    assert colorize("hello", "red", False) == "hello"


def test_colorize_wraps_when_enabled() -> None:
    out = colorize("hello", "red", True)
    assert "hello" in out
    assert "\x1b[" in out
    assert out.endswith("\x1b[0m")


def test_colorize_unknown_color_is_noop() -> None:
    assert colorize("hello", "chartreuse", True) == "hello"


def test_render_finding_plain_contains_location_and_message() -> None:
    f = Finding(path="models/x.sql", line=12, severity="error", message="no description")
    out = render_finding(f, color=False)
    assert "models/x.sql:12" in out
    assert "[error]" in out
    assert "no description" in out
    assert "\x1b[" not in out  # no ANSI when color disabled


def test_render_finding_includes_code() -> None:
    f = Finding(path="models/x.sql", line=3, code="L001", message="bad")
    out = render_finding(f, color=False)
    assert "L001" in out


def test_render_finding_colored_contains_ansi() -> None:
    f = Finding(path="models/x.sql", line=12, severity="warn", message="heads up")
    out = render_finding(f, color=True)
    assert "\x1b[" in out
    assert "models/x.sql:12" in out
    assert "heads up" in out


@pytest.mark.parametrize(
    "severity,code",
    [
        ("error", "\x1b[31m"),
        ("warn", "\x1b[33m"),
        ("ok", "\x1b[32m"),
        ("info", "\x1b[36m"),
    ],
)
def test_severity_color_mapping(severity: str, code: str) -> None:
    f = Finding(path="m.sql", line=1, severity=severity, message="x")
    out = render_finding(f, color=True)
    assert code in out


def test_render_findings_writes_to_stdout_stream() -> None:
    findings = [
        Finding(path="a.sql", line=1, message="one"),
        Finding(path="b.sql", line=2, message="two"),
    ]
    buf = io.StringIO()
    render_findings(findings, color=False, stream=buf)
    lines = buf.getvalue().strip().split("\n")
    assert len(lines) == 2
    assert "a.sql:1" in lines[0]
    assert "b.sql:2" in lines[1]


def test_render_headline_writes_to_stream() -> None:
    buf = io.StringIO()
    render_headline("all good", color=False, severity="ok", stream=buf)
    assert buf.getvalue().strip() == "all good"


def test_render_headline_colored() -> None:
    buf = io.StringIO()
    render_headline("uh oh", color=True, severity="error", stream=buf)
    out = buf.getvalue()
    assert "uh oh" in out
    assert "\x1b[31m" in out


def test_render_file_header_sqlfluff_shape() -> None:
    buf = io.StringIO()
    render_file_header("product: demand", "FAIL", color=False, stream=buf)
    assert buf.getvalue().strip() == "== [product: demand] FAIL"


def test_render_file_header_uppercases_status() -> None:
    buf = io.StringIO()
    render_file_header("models/x.sql", "fail", color=False, stream=buf)
    assert "== [models/x.sql] FAIL" in buf.getvalue()


def test_render_file_header_default_status_is_fail() -> None:
    buf = io.StringIO()
    render_file_header("p", color=False, stream=buf)
    assert buf.getvalue().strip() == "== [p] FAIL"


def test_render_file_header_colored_uses_severity() -> None:
    buf = io.StringIO()
    render_file_header("p", "FAIL", color=True, severity="error", stream=buf)
    out = buf.getvalue()
    assert "\x1b[31m" in out  # error -> red
    assert "== [p] FAIL" in out


def test_render_file_header_no_ansi_when_color_off() -> None:
    buf = io.StringIO()
    render_file_header("p", "FAIL", color=True, severity="error", stream=buf)
    plain = io.StringIO()
    render_file_header("p", "FAIL", color=False, severity="error", stream=plain)
    assert "\x1b[" not in plain.getvalue()


def test_render_note_indents_and_dims() -> None:
    buf = io.StringIO()
    render_note("see: https://example.com", color=False, stream=buf)
    assert buf.getvalue() == "    see: https://example.com\n"  # default 4-space indent


def test_render_note_custom_indent() -> None:
    buf = io.StringIO()
    render_note("guidance", color=False, indent=8, stream=buf)
    assert buf.getvalue() == "        guidance\n"


def test_render_note_colored_is_dimmed() -> None:
    buf = io.StringIO()
    render_note("ctx", color=True, stream=buf)
    out = buf.getvalue()
    assert "\x1b[2m" in out  # dim
    assert "ctx" in out
