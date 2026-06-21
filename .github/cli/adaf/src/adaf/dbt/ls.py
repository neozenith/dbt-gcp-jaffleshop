"""``dbt ls`` subprocess helpers — the single home for selector resolution.

Flavours, all shelling out to ``dbt ls`` (full dbt grammar, honoured by dbt itself rather than
re-implemented here):

* ``ls_select_exclude_paths`` — project-relative model ``.sql`` paths for inline ``--select`` /
  ``--exclude`` expressions, for the file-scoped gates' optional dbt filter.
* ``ls_model_paths`` — project-relative model ``.sql`` paths for a NAMED selector (``--selector``),
  for the data-product / defer flows.
* ``ls_member_ids`` — ``unique_id`` of every resource in a named selector (``--output json``), for
  the sdag viewer's membership mapping and the boundary checks.
* ``ls_select_paths`` — model ``.sql`` paths for an inline ``--select`` against a ``--state``
  baseline (defer-diff's authoritative ``state:modified+`` built set).
"""

# Standard Library
import json
import re
from pathlib import Path

# Local
from adaf.dbt.runner import run_dbt

# Leading dbt log timestamp the Cloud CLI prefixes onto every stdout line: ``HH:MM:SS`` with an
# optional ``.mmm``/``,mmm`` fraction, then whitespace. dbt-core's clean output has no prefix, so the
# pattern only fires when present and otherwise passes the line through unchanged.
_LOG_PREFIX_RE = re.compile(r"^\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+")


def _strip_log_prefix(line: str) -> str:
    """Drop a leading dbt Cloud CLI log-timestamp token from ``line`` (no-op when absent)."""
    return _LOG_PREFIX_RE.sub("", line)


def _run_dbt_ls(extra_args: list[str], *, cwd: Path | None = None, target: str | None = None) -> str:
    """Run ``dbt ls --quiet <extra_args>`` and return stdout (fails loud via ``runner.run_dbt``).

    ``target`` adds ``--target <t>`` so the resolution (and any ``state:modified`` comparison)
    runs under the same dbt target as the manifests it compares.
    """
    args = ["ls", "--quiet", *extra_args]
    if target is not None:
        args += ["--target", target]
    return run_dbt(args, cwd=cwd)


def _sql_paths(out: str) -> set[str]:
    """Keep the ``.sql`` lines of ``dbt ls --output path`` stdout, log-prefix stripped."""
    return {p for line in out.splitlines() if (p := _strip_log_prefix(line.strip())).endswith(".sql")}


def ls_select_exclude_paths(
    select: list[str], exclude: list[str], *, cwd: Path | None = None, target: str | None = None
) -> set[str]:
    """Model ``.sql`` paths matching inline ``--select`` / ``--exclude`` expressions.

    Multiple ``--select`` union (dbt's own behaviour); ``--exclude`` subtracts. Used by the
    file-scoped checks to intersect the changed/all scope with a dbt selector filter.
    """
    extra = ["--resource-type", "model", "--output", "path"]
    for selector in select:
        extra += ["--select", selector]
    for selector in exclude:
        extra += ["--exclude", selector]
    return _sql_paths(_run_dbt_ls(extra, cwd=cwd, target=target))


def ls_model_paths(
    selector: str, *, cwd: Path | None = None, state_dir: Path | None = None, target: str | None = None
) -> set[str]:
    """Project-relative model ``.sql`` paths for a NAMED ``selector`` (matches git's changed-file paths).

    When ``state_dir`` is given, dbt is run with ``--state <dir> --defer`` so unchanged refs
    resolve to that baseline manifest (see ``adaf.dbt.defer``).
    """
    extra = ["--resource-type", "model", "--output", "path", "--selector", selector]
    if state_dir is not None:
        extra += ["--state", str(state_dir), "--defer"]
    return _sql_paths(_run_dbt_ls(extra, cwd=cwd, target=target))


def ls_select_paths(select: str, *, state_dir: Path, cwd: Path | None = None, target: str | None = None) -> set[str]:
    """Model ``.sql`` paths matching an inline ``--select`` expr against a ``--state`` baseline.

    Used by ``defer-diff`` to get dbt's authoritative ``state:modified+`` (built) set — the
    models that differ from the defer target and would actually be built, not deferred.
    """
    extra = ["--resource-type", "model", "--output", "path", "--select", select, "--state", str(state_dir), "--defer"]
    return _sql_paths(_run_dbt_ls(extra, cwd=cwd, target=target))


def ls_member_ids(
    selector: str, *, cwd: Path | None = None, state_dir: Path | None = None, target: str | None = None
) -> set[str]:
    """``unique_id`` of every resource dbt resolves for a NAMED ``selector``.

    When ``state_dir`` is given, dbt is run with ``--state <dir> --defer`` so the selector resolves
    against that baseline manifest (mirrors ``ls_model_paths`` — lets a deferred run, or a
    ``state:``-based selector, resolve correctly).
    """
    extra = ["--selector", selector, "--output", "json", "--output-keys", "unique_id"]
    if state_dir is not None:
        extra += ["--state", str(state_dir), "--defer"]
    out = _run_dbt_ls(extra, cwd=cwd, target=target)
    uids: set[str] = set()
    for line in out.splitlines():
        line = _strip_log_prefix(line.strip())
        if line.startswith("{"):
            uids.add(json.loads(line)["unique_id"])
    return uids
