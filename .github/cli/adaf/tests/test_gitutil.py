# Standard Library
from pathlib import Path

# Local
from adaf.gitutil import dirs_of


def test_dirs_of_dedupes_and_sorts():
    files = [
        Path("models/staging/a.sql"),
        Path("models/staging/b.sql"),
        Path("models/marts/c.sql"),
    ]
    assert [str(d) for d in dirs_of(files)] == ["models/marts", "models/staging"]


def test_dirs_of_empty_returns_empty():
    assert dirs_of([]) == []
