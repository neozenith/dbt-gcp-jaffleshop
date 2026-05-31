"""Shared rendering for check reports.

A "report" is any object exposing three things:

* ``ok: bool``                         — did the check pass?
* ``to_dict() -> dict``                — the machine payload for ``--json``
* ``human_lines() -> list[(int, str)]``— (logging level, message) pairs for humans

This duck-typed contract lets every command share one render path and keeps the
human/JSON split in exactly one place.
"""

# Standard Library
import json
import logging
import sys

log = logging.getLogger(__name__)


def render(report, *, as_json: bool) -> int:
    """Emit a report (JSON to stdout, or human lines to stderr) and return its exit code."""
    if as_json:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
    else:
        for level, line in report.human_lines():
            log.log(level, line)
    return 0 if report.ok else 1
