"""Logging configuration. ``--debug`` swaps the terse human format for a verbose
one with module:func:line context (matches the sibling ``adaf`` tool). Human and
log lines go to stderr; any ``--json`` payload is the only thing on stdout, so
``obs ... --json | jq`` stays clean."""

import logging
import sys

_HUMAN_FORMAT = "%(message)s"
_DEBUG_FORMAT = "%(asctime)s::%(name)s::%(levelname)s::%(module)s:%(funcName)s:%(lineno)d| %(message)s"


def configure_logging(debug: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format=_DEBUG_FORMAT if debug else _HUMAN_FORMAT,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
