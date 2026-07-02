"""All git interactions for adaf — changed-file detection + worktree lifecycle.

Both the file-scoped gates (``changed_model_files``) and the defer-target builder
(``resolve_sha`` / worktree helpers) call in here, so the git subprocess surface
lives in exactly one module.
"""

from adaf.git.gitutil import (
    add_worktree,
    changed_model_files,
    dirs_of,
    remove_worktree,
    resolve_sha,
    run_git,
)

__all__ = [
    "add_worktree",
    "changed_model_files",
    "dirs_of",
    "remove_worktree",
    "resolve_sha",
    "run_git",
]
