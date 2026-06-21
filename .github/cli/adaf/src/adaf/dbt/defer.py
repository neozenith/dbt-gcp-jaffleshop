"""Build + cache a *defer-target* manifest from a git ref, so dbt's ``--defer`` can be used.

Given a git ref (tag / branch / sha), check it out into a throwaway worktree (never disturbing
the working tree — see ``adaf.gitutil``), install THAT ref's own packages, run ``dbt parse``, and
cache the resulting ``manifest.json`` under ``tmp/`` keyed on the **resolved commit sha**. A
moving branch like ``main`` reparses when it advances (its sha changes → cache miss); a fixed
tag/sha reuses the cache forever.

Two delegations keep this module thin: git (worktree lifecycle, sha resolution) lives in
``adaf.gitutil``; the dbt invocations (``deps``, ``parse``) live in ``adaf.dbt.runner``.

``DBT_PR_NUMBER`` is forced empty for the parse so the state manifest never bakes in a
PR-scoped schema name — otherwise ``state:modified`` against it would flag every model.
"""

# Standard Library
import logging
from pathlib import Path

# Local
from adaf import config
from adaf.dbt.runner import dbt_deps, dbt_parse
from adaf.gitutil import add_worktree, remove_worktree, resolve_sha

log = logging.getLogger(__name__)

_WT_ROOT = Path("tmp") / "adaf_cache" / "_wt"  # throwaway worktrees
_DEFER_ROOT = Path("tmp") / "adaf_cache" / "defer"  # cached defer-target manifests, per sha


def defer_state_dir(ref: str, *, root: Path | None = None, force: bool = False, target: str | None = None) -> Path:
    """Return the dir holding a parsed ``manifest.json`` for ``ref`` — building + caching it
    in an isolated worktree on a cache miss. Pass to dbt as ``--state <dir> --defer``.

    ``target`` selects the dbt target for the parse; it changes the schema names baked into the
    manifest, so the cache is keyed on ``(sha, target)`` — the same commit parsed under ``dev`` vs
    ``test`` yields different defer targets and must not collide.
    """
    root = root or config.project_root()
    sha = resolve_sha(ref, cwd=root)
    state_dir = root / _DEFER_ROOT / sha / (target or "_default")
    manifest = state_dir / "manifest.json"
    if manifest.exists() and not force:
        log.debug(
            "defer: cached defer-target for %s (%s, target=%s) — %s", ref, sha[:10], target or "_default", state_dir
        )
        return state_dir

    log.debug(
        "defer: building defer-target for %s (%s, target=%s) in an isolated worktree…",
        ref,
        sha[:10],
        target or "_default",
    )
    wt = root / _WT_ROOT / sha
    add_worktree(wt, sha, cwd=root)
    try:
        # Install THIS ref's own packages — never symlink the working tree's dbt_packages,
        # since packages.yml / package-lock can differ between commits (a wrong dep graph
        # would silently distort the defer target).
        log.info("defer: installing packages for %s (dbt deps in the worktree)…", sha[:10])
        dbt_deps(project_dir=wt, cwd=root)
        state_dir.mkdir(parents=True, exist_ok=True)
        dbt_parse(
            cwd=root,
            project_dir=wt,
            profiles_dir=root,
            target=target,
            target_path=state_dir,
            extra_env={"DBT_PR_NUMBER": ""},  # don't bake a PR-scoped schema into the state
        )
        if not manifest.exists():
            raise RuntimeError(f"defer: dbt parse produced no manifest at {manifest}")
    finally:
        remove_worktree(wt, cwd=root)
    log.info("defer: cached %s", manifest)
    return state_dir
