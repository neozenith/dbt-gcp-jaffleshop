"""Static configuration + dbt-project discovery for the Automated Data Assurance
Framework (``adaf``) CLI.

The CLI may run from the repo root (CI) or a Makefile target, so the dbt project
root is *discovered* (walk up for ``dbt_project.yml``), never assumed. ``main()`` calls
``set_project_root()`` once; every other module reads it via ``config.project_root()`` (or
takes an explicit ``cwd`` so the pure logic stays unit-testable). State lives on a holder
instance (``_state``) rather than a module global — see ADR-0013.
"""

# Standard Library
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class _State:
    """Process-wide mutable state. Held on an instance so ``set_project_root`` can update it
    by *attribute assignment* — no ``global`` rebinding of a module name (which is forbidden)."""

    project_root: Path = field(default_factory=Path.cwd)


_state = _State()


def project_root() -> Path:
    """The discovered dbt project root (defaults to cwd until ``set_project_root`` runs)."""
    return _state.project_root


# Env var that overrides discovery (parallels dbt's own --project-dir / DBT_PROJECT_DIR).
PROJECT_DIR_ENV = "ADAF_PROJECT_DIR"

# Git ref the "changed models" detection diffs against (merge-base with HEAD).
# Override per-invocation with --base-ref; CI passes the PR base (e.g. origin/main).
DEFAULT_BASE_REF = "main"

# NOTE: there is deliberately NO default selector. `--selector` is a required flag so the
# scope (which data product) is always explicit — see AGENTS.md ADR-0003 (superseded) /
# ADR-0012. Each run intersects its file universe with `dbt ls --selector <name>`.

# Pathspec for "what is a model file" (git pathspec: `*` spans directories).
MODEL_GLOB = "models/*.sql"

# Default project-relative paths (resolved against PROJECT_ROOT in main()).
DEFAULT_MANIFEST = Path("target") / "manifest.json"  # coverage checks read this
DEFAULT_SELECTORS = Path("selectors.yml")  # dbt hardcodes this filename (never .yaml)
DEFAULT_SDAG_OUTPUT = Path("tmp") / "sdag"  # where the sdag viewer assets are written

# `gha create` — the per-data-product workflow generator.
DEFAULT_WORKFLOWS_DIR = Path(".github") / "workflows"  # where generated adaf-<product>.yml are written
# The base template is OWNED BY THE CLI (shipped as package data), not a checked-in repo workflow — so
# `gha create` clones a canonical skeleton regardless of what product workflows already exist. Absolute
# (package-relative) path: `under_root` passes it through unchanged. Mirrors the sdag assets pattern.
GHA_ASSETS_DIR = Path(__file__).resolve().parent / "gha" / "assets"
DEFAULT_WORKFLOW_TEMPLATE = GHA_ASSETS_DIR / "workflow-template.yml"

# `gha init` — the reusable composite-action installer. The canonical source for the `adaf-*` composite
# actions is OWNED BY THE CLI (shipped as package data under assets/actions/<name>/...), so a consuming
# repo can re-materialise them with `adaf gha init` and a version-stamped header lets the next run detect
# drift. Mirrors the workflow-template pattern above.
GHA_ACTIONS_ASSETS_DIR = GHA_ASSETS_DIR / "actions"
DEFAULT_ACTIONS_DIR = Path(".github") / "actions"  # where the deployed adaf-<name>/ composite actions live

# `gha init` ALSO deploys the reusable workflow (the parallel job graph the per-product callers `uses:`).
# A reusable workflow MUST live in `.github/workflows/` (GitHub requirement — it can't go under actions/),
# so it ships as a SEPARATE asset tree from the composite actions and deploys to the workflows dir.
GHA_WORKFLOWS_ASSETS_DIR = GHA_ASSETS_DIR / "workflows"


def under_root(path: Path | None) -> Path | None:
    """Resolve a possibly-relative path arg against the project root (absolute paths pass through)."""
    if path is None:
        return None
    p = Path(path)
    return p if p.is_absolute() else project_root() / p


def resolve_project_root(override: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the dbt project root, failing loud if none can be found."""
    cand = override or os.environ.get(PROJECT_DIR_ENV)
    if cand:
        root = Path(cand).expanduser().resolve()
        if not (root / "dbt_project.yml").exists():
            raise RuntimeError(f"--project-dir/{PROJECT_DIR_ENV} '{root}' has no dbt_project.yml")
        return root
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / "dbt_project.yml").exists():
            return d
    raise RuntimeError(
        "could not locate a dbt project: no dbt_project.yml in --project-dir, "
        f"${PROJECT_DIR_ENV}, the cwd ({here}), or any parent. Pass --project-dir."
    )


def set_project_root(override: str | os.PathLike[str] | None = None) -> Path:
    """Discover and record the project root (called once by main()).

    Mutates ``_state.project_root`` by attribute assignment — deliberately NOT a ``global``
    rebind of a module-level name (that anti-pattern is forbidden; see AGENTS.md ADR-0013)."""
    _state.project_root = resolve_project_root(override)
    return _state.project_root
