"""Defer-target helpers: the ``state:modified+`` (``M+``) split and the ``adaf defer-state`` command.

The built-vs-deferred preview that used to live in a standalone ``defer-diff`` subcommand is now part
of ``adaf ls --defer`` (each group splits into a ``built`` / ``deferred`` sub-section). What remains
here is the shared machinery:

* :func:`built_model_paths` — the faithful ``M+`` model paths a deferred ``dbt build`` would rebuild,
  computed offline by :mod:`adaf.dbt.state_modified` against the ``--defer-ref`` (or ``--state``)
  baseline. ``adaf ls --defer`` intersects it with each group to label built vs deferred.
* :func:`cmd_defer_state` — build/cache the defer-target state for a ref and print its ``--state`` dir
  (so CI can feed it to a downstream ``dbt build --state``).
"""

# Standard Library
import argparse
import logging
from pathlib import Path

# Local
from adaf.dbt.defer import defer_state_dir
from adaf.dbt.selection import Selection
from adaf.dbt.state_modified import State, StateModified

log = logging.getLogger(__name__)


def built_model_paths(sel: Selection, manifest: Path, *, root: Path) -> set[str]:
    """The faithful ``M+`` (state:modified+) model ``.sql`` paths vs the ``--defer-ref`` baseline.

    This is the set a deferred ``dbt build`` would REBUILD; every other model in scope is *deferred*
    (its ref resolves to the baseline relation). It is the SAME ``M+`` set ``adaf ls --flags`` seeds
    the build with (so a ``built`` tag can never disagree with the actual build), computed offline by
    :mod:`adaf.dbt.state_modified` against the baseline manifest. ``--state <dir>`` is honoured as the
    baseline when given (no git); otherwise it is built + cached from ``--defer-ref``. Returns the
    full-project path set; the caller intersects it with whichever scope it is grouping.
    """
    baseline = State.load(sel.baseline_state_dir(cwd=root) / "manifest.json")
    current = State.load(manifest)
    return set(StateModified.compare(baseline, current).model_reasons(plus=True))


def _defer_target(args: argparse.Namespace) -> str | None:
    """The target the defer-target parse runs under: ``--defer-target`` if given, else ``--target``."""
    return getattr(args, "defer_target", None) or getattr(args, "target", None)


def cmd_defer_state(args: argparse.Namespace) -> int:
    """Build (or reuse the cache of) the defer-target state for ``--defer-ref`` and print its dir.

    The lone stdout line is the ``--state`` directory, so CI can capture it for a downstream
    ``dbt build --state "$(adaf defer-state …)"``. Progress/logging goes to stderr.
    """
    state_dir = defer_state_dir(args.defer_ref, target=_defer_target(args), force=getattr(args, "force", False))
    print(state_dir)  # stdout: the one machine-readable line (the resolved --state dir)
    return 0
