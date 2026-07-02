"""`adaf gha` — generate per-data-product GitHub Actions workflow entrypoints."""

from adaf.gha.actions import cmd_init
from adaf.gha.commands import cmd_analyse, cmd_create, cmd_update

__all__ = ["cmd_analyse", "cmd_create", "cmd_init", "cmd_update"]
