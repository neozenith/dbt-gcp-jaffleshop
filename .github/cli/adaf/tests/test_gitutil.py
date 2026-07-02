"""Unit tests for the pure git helpers (the subprocess paths aren't exercised here)."""

# Standard Library
from pathlib import Path

# First Party
from adaf.git.gitutil import dirs_of


def test_dirs_of_dedups_and_sorts() -> None:
    files = [
        Path("models/cdm/demand/a.sql"),
        Path("models/cdm/demand/b.sql"),  # same dir as a → deduped
        Path("models/staging/x.sql"),
    ]
    assert dirs_of(files) == [Path("models/cdm/demand"), Path("models/staging")]


def test_dirs_of_empty() -> None:
    assert dirs_of([]) == []
