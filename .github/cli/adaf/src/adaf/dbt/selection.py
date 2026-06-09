"""Model selection — the shared scope/filter logic every check command uses.

A selection resolves to a concrete list of model ``.sql`` file paths (project-relative,
e.g. ``models/staging/stg_orders.sql``) via two composable inputs:

* **Scope** (mutually exclusive): ``--changed-only`` (default) or ``--all``.
    - changed-only → git-changed model files (see gitutil).
    - all         → every ``models/**/*.sql`` on disk.
* **Filter** (optional, dbt-resolved, repeatable): ``--select`` / ``--exclude``.
    When given, the scope is intersected with dbt's own selection result, obtained by
    shelling out to ``dbt ls`` — so the FULL dbt selector grammar (graph operators,
    ``tag:``, ``path:``, unions/intersections, ...) is honoured rather than re-implemented.

Combination examples::

    --changed-only --select staging   → changed models that are also in staging
    --all          --select staging   → every staging model
    --changed-only --exclude tag:wip  → changed models, minus the wip-tagged ones

Multiple ``--select`` union (dbt's own behaviour); ``--exclude`` subtracts.
"""

# Standard Library
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Local
from adaf import config
from adaf.gitutil import changed_model_files


@dataclass
class Selection:
    all_models: bool = False
    base_ref: str = config.DEFAULT_BASE_REF
    select: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    @property
    def has_selectors(self) -> bool:
        return bool(self.select or self.exclude)


def from_args(args) -> Selection:
    """Build a Selection from parsed argparse flags (shared across every leaf command)."""
    return Selection(
        all_models=getattr(args, "all_models", False),
        base_ref=getattr(args, "base_ref", config.DEFAULT_BASE_REF),
        select=list(getattr(args, "select", None) or []),
        exclude=list(getattr(args, "exclude", None) or []),
    )


def describe(selection: Selection) -> str:
    """A short human label for the resolved scope, shown in every report header."""
    scope = "all models" if selection.all_models else f"changed models vs {selection.base_ref}"
    if selection.select:
        scope += f" ∩ select={','.join(selection.select)}"
    if selection.exclude:
        scope += f" − exclude={','.join(selection.exclude)}"
    return scope


def all_model_files(cwd: Path) -> list[Path]:
    """Every ``models/**/*.sql`` on disk, project-relative and sorted."""
    root = Path(cwd)
    return sorted((p.relative_to(root) for p in root.glob("models/**/*.sql")), key=str)


def dbt_ls_paths(select: list[str], exclude: list[str], *, cwd: Path) -> set[str]:
    """Resolve dbt ``--select``/``--exclude`` to a set of model file paths via ``dbt ls``.

    ``--quiet`` suppresses dbt's banner; warnings go to stderr, so capturing stdout and
    keeping only ``.sql`` lines yields a clean path set. Fail loud if dbt errors.
    """
    cmd = ["dbt", "ls", "--quiet", "--resource-type", "model", "--output", "path"]
    for selector in select:
        cmd += ["--select", selector]
    for selector in exclude:
        cmd += ["--exclude", selector]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(
            f"`dbt ls` failed (exit {proc.returncode}):\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return {line.strip() for line in proc.stdout.splitlines() if line.strip().endswith(".sql")}


def resolve_model_files(selection: Selection, *, cwd: Path | None = None) -> list[Path]:
    """Resolve a Selection to a concrete, sorted list of model ``.sql`` paths."""
    cwd = cwd or config.PROJECT_ROOT
    if selection.all_models:
        universe = all_model_files(cwd)
    else:
        universe = changed_model_files(selection.base_ref, cwd=cwd)
    if selection.has_selectors:
        selected = dbt_ls_paths(selection.select, selection.exclude, cwd=cwd)
        universe = [p for p in universe if str(p) in selected]
    return sorted(set(universe), key=str)
