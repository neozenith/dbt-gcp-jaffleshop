"""ANSI colour + emoji styling for the CLI's OWN output (verdicts, headers, per-item rows).

Underlying-tool transcripts carry their own native colour (captured via a pty — see
``toollog``); this module styles the lines *we* generate. Colour is gated on a single
module flag set once at startup from ``--color`` (auto/always/never), where ``auto`` means
"stderr is a TTY and NO_COLOR is unset". When colour is off, helpers return plain text and
``strip_ansi`` cleans the tool transcripts too, so piped/redirected output stays readable.

Each check is given a distinct emoji label so sections are visually separable, and pass/fail
use ✅/❌ in green/red.
"""

# Standard Library
import os
import re
import sys

_ENABLED = False

PASS = "✅"
FAIL = "❌"

# One emoji per check, so each section is instantly identifiable in `check all`.
EMOJI = {
    "deprecations": "🧹",
    "lint": "🔍",
    "format": "🎨",
    "docs": "📄",
    "doc-columns": "📑",
    "tests": "🧪",
    "boundaries": "🧭",
    "system-boundaries": "🛡️",
}

# Glyph per boundary classification, used by the data-product analysis. inbound = data enters the
# product, outbound = data leaves it, both = a shared crossing node, internal = fully interior.
BOUNDARY_GLYPH = {
    "inbound": "⬇",
    "outbound": "⬆",
    "both": "⇅",
    "internal": "·",
}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def configure(mode: str = "auto") -> None:
    """Set the global colour state from ``--color`` (auto/always/never)."""
    global _ENABLED
    if mode == "always":
        _ENABLED = True
    elif mode == "never":
        _ENABLED = False
    else:  # auto
        _ENABLED = sys.stderr.isatty() and os.environ.get("NO_COLOR") is None


def enabled() -> bool:
    return _ENABLED


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _wrap(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _ENABLED else text


def green(s: str) -> str:
    return _wrap("32", s)


def red(s: str) -> str:
    return _wrap("31", s)


def yellow(s: str) -> str:
    return _wrap("33", s)


def cyan(s: str) -> str:
    return _wrap("36", s)


def magenta(s: str) -> str:
    return _wrap("35", s)


def bold(s: str) -> str:
    return _wrap("1", s)


def dim(s: str) -> str:
    return _wrap("2", s)


# --- semantic helpers the reports use -----------------------------------------
def section(name: str) -> str:
    """Emoji + bold check name — the section label."""
    return f"{EMOJI.get(name, '•')} {bold(cyan(name))}"


def passed(msg: str) -> str:
    return green(f"{PASS} {msg}")


def failed(msg: str) -> str:
    return red(f"{FAIL} {msg}")


def pass_item(msg: str) -> str:
    return green(f"   {PASS} {msg}")


def fail_item(msg: str) -> str:
    return red(f"   {FAIL} {msg}")


# Colour per boundary classification — distinct hues so the four roles are scannable. inbound/cyan
# (incoming), outbound/yellow (outgoing), both/magenta (a crossing in both directions), internal/dim.
_BOUNDARY_COLOUR = {"inbound": cyan, "outbound": yellow, "both": magenta, "internal": dim}


def boundary_item(kind: str, msg: str) -> str:
    """A single classified node row: glyph + message, coloured by classification."""
    glyph = BOUNDARY_GLYPH.get(kind, "·")
    colour = _BOUNDARY_COLOUR.get(kind, dim)
    return colour(f"   {glyph} {msg}")
