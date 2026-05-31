"""Changed-file detection — the Python port of the Makefile's CHANGED_MODELS snippet.

The original shell was the single source of truth for "what changed vs BASE_REF":

    git diff --name-only --relative --diff-filter=d $(git merge-base BASE_REF HEAD) -- 'models/*.sql'
    git ls-files --others --exclude-standard -- 'models/*.sql'
    | sort -u

i.e. model SQL differing from the merge-base in ANY git state — committed, staged,
unstaged (the ``git diff``) plus untracked-new (the ``ls-files --others``). We
reproduce it exactly so the CLI and any remaining Make targets agree on the set.
``--relative`` yields paths rooted at the dbt project (``models/...``), which is
exactly how dbt's manifest keys ``original_file_path`` — so no path translation is
needed downstream.
"""

# Standard Library
import subprocess
from pathlib import Path

# Local
from cicd_cli import config


def _git(args: list[str], cwd: Path) -> list[str]:
    """Run a git command, fail loud on non-zero, return non-empty stdout lines."""
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def changed_model_files(base_ref: str, *, cwd: Path | None = None, glob: str | None = None) -> list[Path]:
    """Model files changed vs the merge-base of ``base_ref`` and HEAD, in any git state."""
    cwd = cwd or config.PROJECT_ROOT
    glob = glob or config.MODEL_GLOB
    merge_base = _git(["merge-base", base_ref, "HEAD"], cwd)[0]
    tracked = _git(["diff", "--name-only", "--relative", "--diff-filter=d", merge_base, "--", glob], cwd)
    untracked = _git(["ls-files", "--others", "--exclude-standard", "--", glob], cwd)
    return [Path(p) for p in sorted(set(tracked) | set(untracked))]


def dirs_of(files: list[Path]) -> list[Path]:
    """Unique parent directories of ``files``, sorted — the file→folder lift, deduped.

    Pure (no git), so it is unit-testable in isolation. This is the Python form of
    the Makefile's ``sed 's#/[^/]*$##' | sort -u``.
    """
    return sorted({f.parent for f in files}, key=str)


def changed_model_dirs(base_ref: str, **kwargs) -> list[Path]:
    """Unique parent folders of the changed model files."""
    return dirs_of(changed_model_files(base_ref, **kwargs))
