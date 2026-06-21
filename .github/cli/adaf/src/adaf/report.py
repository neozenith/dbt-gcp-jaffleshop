"""Shared reporting substrate for the workflow commands (list, defer-diff, deprecations, sqlfluff).

Two cross-cutting concerns live here so every gate renders findings the same way:

* **Editor-clickable locations** — a finding carries ``path``/``line``/``col`` and
  :func:`format_location` renders the ``path:line:col`` form editors and CI logs can jump to.
* **Colourised TUI output** — :func:`should_colorize` resolves the ``--color {auto,always,never}``
  flag against the target stream (honouring ``NO_COLOR``), and the render helpers paint
  severity tags and dim the path only when colour is enabled.

The CLI's output convention is preserved: a one-line headline goes to STDERR
(:func:`render_headline`) and the findings list goes to STDOUT (:func:`render_findings`).
The argparse flag itself is wired by the command layer — this module only exposes the
resolver so a command can compute ``color = should_colorize(args.color, sys.stdout)``.

This is the substrate the data-product workflow commands (``list``, ``defer-diff``) render through.
The catalogue checks (``check …``) keep their own ``utils.style`` / ``utils.formatting`` rendering.
"""

# Standard Library
import os
import shlex
import sys
from dataclasses import dataclass
from typing import Literal, Protocol, TextIO

ColorMode = Literal["auto", "always", "never"]

Severity = Literal["error", "warn", "ok", "info"]

# ANSI SGR codes keyed by logical colour name. ``reset`` closes any open sequence.
_ANSI: dict[str, str] = {
    "red": "\x1b[31m",
    "darkred": "\x1b[38;5;88m",  # deep red — `ls --paths` false-positive highlight
    "yellow": "\x1b[33m",
    "green": "\x1b[32m",
    "blue": "\x1b[34m",
    "cyan": "\x1b[36m",
    "dim": "\x1b[2m",
    "grey": "\x1b[90m",
    # `list` distinguishes its sections by HUE (not grey shades, which read too alike): selector
    # models stay neutral (white / bright-white when git-changed), --upstream nodes are amber
    # (yellow), --downstream nodes are green — matching the retro DAG diagram's palette.
    "white": "\x1b[37m",
    "bright": "\x1b[97m",
    "reset": "\x1b[0m",
}

# Severity -> palette colour for the bracketed tag.
_SEVERITY_COLOR: dict[str, str] = {
    "error": "red",
    "warn": "yellow",
    "ok": "green",
    "info": "cyan",
}


class _Stream(Protocol):
    """Minimal stream contract used for colour resolution (``isatty`` only)."""

    def isatty(self) -> bool: ...


@dataclass(frozen=True)
class Finding:
    """A single reportable observation about a file, optionally pinned to a line/column."""

    path: str
    line: int | None = None
    col: int | None = None
    severity: str = "error"
    code: str | None = None
    message: str = ""
    path_color: str | None = None  # override the path colour (default "dim"); e.g. "grey" for context nodes


def format_location(path: str, line: int | None = None, col: int | None = None) -> str:
    """Render an editor-clickable location: ``path:line:col`` / ``path:line`` / ``path``.

    A column is only appended when a line is also present (a bare column has no anchor).
    """
    if line is None:
        return path
    if col is None:
        return f"{path}:{line}"
    return f"{path}:{line}:{col}"


def should_colorize(mode: ColorMode, stream: _Stream) -> bool:
    """Resolve whether to emit ANSI colour for ``mode`` targeting ``stream``.

    * ``"always"`` — always colour, even when redirected.
    * ``"never"`` — never colour.
    * ``"auto"`` — colour only when ``stream`` is a TTY.

    The ``NO_COLOR`` environment variable (set to any value) forces colour off for every
    mode except ``"always"`` — see https://no-color.org/.
    """
    if mode == "always":
        return True
    if mode == "never":
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    return stream.isatty()


def colorize(text: str, color: str, enabled: bool) -> str:
    """Wrap ``text`` in the ANSI sequence for ``color``; a no-op when ``enabled`` is False."""
    if not enabled:
        return text
    code = _ANSI.get(color)
    if code is None:
        return text
    return f"{code}{text}{_ANSI['reset']}"


def render_finding(f: Finding, *, color: bool) -> str:
    """Render one finding as ``path:line: [severity] message`` (path dimmed, tag coloured)."""
    location = colorize(format_location(f.path, f.line, f.col), f.path_color or "dim", color)
    tag_color = _SEVERITY_COLOR.get(f.severity, "info")
    tag = colorize(f"[{f.severity}]", tag_color, color)
    parts = [f"{location}:", tag]
    if f.code:
        parts.append(f.code)
    if f.message:
        parts.append(f.message)
    return " ".join(parts)


def render_findings(findings: list[Finding], *, color: bool, stream: TextIO | None = None) -> None:
    """Write each finding to STDOUT (or ``stream``), one per line — the machine-readable list."""
    out = stream if stream is not None else sys.stdout
    for f in findings:
        print(render_finding(f, color=color), file=out)


def render_headline(text: str, *, color: bool, severity: str = "info", stream: TextIO | None = None) -> None:
    """Write a one-line, severity-coloured headline to STDERR (or ``stream``).

    Keeps the CLI's split intact: humans read this on STDERR while STDOUT stays the findings list.
    """
    err = stream if stream is not None else sys.stderr
    print(colorize(text, _SEVERITY_COLOR.get(severity, "info"), color), file=err)


def render_file_header(
    label: str,
    status: str = "FAIL",
    *,
    color: bool,
    severity: str = "error",
    stream: TextIO | None = None,
) -> None:
    """Write a sqlfluff-style ``== [<label>] <STATUS>`` group delimiter to STDERR (or ``stream``).

    Mirrors sqlfluff's per-file ``== [path] FAIL`` header: the ``==`` prefix and bracketed label
    delimit a group of findings and the uppercased status word carries the severity colour. Like
    :func:`render_headline` it lands on STDERR so the findings list on STDOUT stays a clean,
    pipeable stream — it is a human-facing delimiter, not a finding.
    """
    err = stream if stream is not None else sys.stderr
    head = f"== [{label}] {status.upper()}"
    print(colorize(head, _SEVERITY_COLOR.get(severity, "info"), color), file=err)


def render_note(text: str, *, color: bool, indent: int = 4, stream: TextIO | None = None) -> None:
    """Write an indented, dimmed continuation line under a finding to STDOUT (or ``stream``).

    Matches dbt-autofix's nested sub-lines: extra context for a finding (a rule's guidance, a
    ``see:`` doc URL) sits below it at ``indent`` spaces, dimmed so it reads as secondary. It is a
    continuation of a finding — not a new finding — so it stays on STDOUT with the findings list.
    """
    out = stream if stream is not None else sys.stdout
    print(colorize(f"{' ' * indent}{text}", "dim", color), file=out)


def print_commands(label: str, argvs: list[list[str]], *, color: bool) -> int:
    """Print each subprocess command verbatim instead of running it — one runnable, shell-quoted
    line to STDOUT (pipeable), a headline to STDERR. Lets a user inspect, copy, or run the exact
    command adaf would have shelled out to. Paths are relative to the dbt project root, so the
    printed commands are meant to be run from there. Always returns 0 (nothing was executed).
    """
    render_headline(
        f"# {label} — {len(argvs)} command(s); run from the dbt project root", color=color, severity="info"
    )
    for argv in argvs:
        print(shlex.join(argv))
    return 0


def render_table(headers: list[str], rows: list[list[str]], *, aligns: list[str] | None = None) -> str:
    """Render a box-drawn TUI table (stdlib only). ``aligns[i]`` is ``"l"`` or ``"r"`` per column."""
    cols = len(headers)
    al = aligns or ["l"] * cols
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i]) for i in range(cols)]

    def rule(left: str, mid: str, right: str) -> str:
        return left + mid.join("─" * (w + 2) for w in widths) + right

    def row(cells: list[str]) -> str:
        out_cells = [(cells[i].rjust(widths[i]) if al[i] == "r" else cells[i].ljust(widths[i])) for i in range(cols)]
        return "│ " + " │ ".join(out_cells) + " │"

    body = [row(r) for r in rows]
    return "\n".join([rule("┌", "┬", "┐"), row(headers), rule("├", "┼", "┤"), *body, rule("└", "┴", "┘")])
