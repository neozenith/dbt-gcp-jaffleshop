"""Logging configuration for the cicd-cli.

Per the project Python RULES, human-facing messages go through ``logging`` (never
``print``) and are written to **stderr**. This keeps **stdout** clean for the
``--json`` machine payload, so a caller can safely do ``... --json | jq`` without
log lines corrupting the stream.
"""

# Standard Library
import logging
import sys


def configure_logging(verbose: bool = False) -> None:
    """Send bare (unprefixed) log lines to stderr; stdout is reserved for JSON output."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
