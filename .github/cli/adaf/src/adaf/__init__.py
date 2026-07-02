"""ADAF — the Automated Data Assurance Framework CLI."""

# Standard Library
from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth: the version declared in pyproject.toml (read from installed metadata),
    # so `gha init`'s managed-asset banner never drifts from a hand-maintained constant.
    __version__ = version("adaf")
except PackageNotFoundError:  # pragma: no cover - only when running from a non-installed checkout
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
