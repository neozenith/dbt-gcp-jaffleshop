"""Root discovery — the contract that lets `tfs` run from anywhere (a global
`uv tool install`, a repo subdir, CI) without ever assuming a fixed layout.

Two roots are resolved INDEPENDENTLY:

  * infra_root — the dir holding ``config.yml`` + ``stacks/``. All stack/module
    paths are relative to this. Found by walking UP from cwd (or an explicit
    override), so it works whether you're in ``infra/``, ``infra/stacks/x/``, …

  * repo_root  — the dir holding ``.github/``. Found via
    ``git rev-parse --show-toplevel``, NEVER as ``infra_root.parent``. The old
    ``tf-stack.py`` hardcoded ``working_dir / ".." / ".github"``; that assumption
    breaks the moment infra/ and .github/ aren't siblings, so it's gone.
"""

import logging
import os
import subprocess
from pathlib import Path
from shlex import split

from tfs.errors import InfraRootNotFoundError

log = logging.getLogger(__name__)

INFRA_ROOT_ENV = "TFS_INFRA_ROOT"


def _is_infra_root(path: Path) -> bool:
    """An infra root has both the per-env config and the stacks/ directory."""
    return (path / "config.yml").is_file() and (path / "stacks").is_dir()


def find_infra_root(start: Path | None = None, override: str | None = None) -> Path:
    """Locate the infra root. Resolution order (fails loud, never guesses):

    1. ``override`` (the ``--infra-root`` flag)
    2. the ``TFS_INFRA_ROOT`` environment variable
    3. cwd and each of its ancestors, first match wins
    """
    candidate = override or os.environ.get(INFRA_ROOT_ENV)
    if candidate:
        root = Path(candidate).expanduser().resolve()
        if not _is_infra_root(root):
            raise InfraRootNotFoundError(f"{root} is not an infra root — it must contain both config.yml and stacks/.")
        log.debug("infra root (explicit): %s", root)
        return root

    start = (start or Path.cwd()).resolve()
    for path in (start, *start.parents):
        if _is_infra_root(path):
            log.debug("infra root (discovered): %s", path)
            return path

    raise InfraRootNotFoundError(
        f"No infra root (a directory with config.yml + stacks/) found at or above {start}.\n"
        f"  Run tfs from within the infra/ tree, set {INFRA_ROOT_ENV}, or pass --infra-root <path>."
    )


def find_repo_root(infra_root: Path) -> Path:
    """Locate the repo root (where ``.github/`` lives), independent of how deep
    infra_root sits. Prefers git's toplevel; falls back to walking up for a
    ``.github/`` dir, then to infra_root itself — only when there's no git repo."""
    try:
        out = subprocess.check_output(
            split("git rev-parse --show-toplevel"),
            cwd=infra_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        repo_root = Path(out).resolve()
        log.debug("repo root (git): %s", repo_root)
        return repo_root
    except (subprocess.CalledProcessError, FileNotFoundError):
        log.debug("git toplevel unavailable; walking up from %s for a .github/ dir", infra_root)
        for path in (infra_root, *infra_root.parents):
            if (path / ".github").is_dir():
                return path
        return infra_root
