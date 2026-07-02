"""git subprocess helpers — the single home for every git call adaf makes."""

# Standard Library
import shutil
import subprocess
from pathlib import Path

# Local
from adaf import config


def run_git(args: list[str], *, cwd: Path) -> str:
    """Run ``git -C <cwd> <args>``; fail loud on non-zero, return raw stdout."""
    proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def _nonempty_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.strip()]


# ─── Changed-file detection ──────────────────────────────────────────────────


def changed_model_files(base_ref: str, *, cwd: Path | None = None, glob: str | None = None) -> list[Path]:
    """Model files changed vs the merge-base of ``base_ref`` and HEAD, in any git state."""
    cwd = cwd or config.project_root()
    glob = glob or config.MODEL_GLOB
    merge_base = _nonempty_lines(run_git(["merge-base", base_ref, "HEAD"], cwd=cwd))[0]

    # tracked are the "modified" files.
    tracked = _nonempty_lines(
        run_git(["diff", "--name-only", "--relative", "--diff-filter=d", merge_base, "--", glob], cwd=cwd)
    )

    # untracked are potentially "new" files.
    untracked = _nonempty_lines(run_git(["ls-files", "--others", "--exclude-standard", "--", glob], cwd=cwd))
    return [Path(p) for p in sorted(set(tracked) | set(untracked))]


def dirs_of(files: list[Path]) -> list[Path]:
    """Unique parent directories of ``files``, sorted — the file→folder lift, deduped."""
    return sorted({f.parent for f in files}, key=str)


# ─── Worktree lifecycle ──────────────────────────────────────────────────────
# Used to checkout temporary copies of dbt deferred state base references.


def resolve_sha(ref: str, *, cwd: Path) -> str:
    """Resolve a git ``ref`` (branch/tag/sha) to its full commit sha (so a moving branch re-keys)."""
    return run_git(["rev-parse", f"{ref}^{{commit}}"], cwd=cwd).strip()


def add_worktree(wt: Path, sha: str, *, cwd: Path) -> None:
    """Add a detached worktree at ``wt`` checked out to ``sha`` (replacing any stale one)."""
    if wt.exists():
        remove_worktree(wt, cwd=cwd)
    wt.parent.mkdir(parents=True, exist_ok=True)
    run_git(["worktree", "add", "--detach", str(wt), sha], cwd=cwd)


def remove_worktree(wt: Path, *, cwd: Path) -> None:
    """Remove a worktree, falling back to manual rmtree + prune if git refuses."""
    try:
        run_git(["worktree", "remove", "--force", str(wt)], cwd=cwd)
    except RuntimeError:
        shutil.rmtree(wt, ignore_errors=True)
        run_git(["worktree", "prune"], cwd=cwd)
