"""Static configuration, default paths, and dbt-project discovery for ``adaf``.

The deterministic checks operate on a dbt project (manifest/catalog/selectors,
``git`` over ``models/``). Unlike the old in-tree ``cicd_cli`` — which assumed the
process cwd WAS the project root — ``adaf`` is an installed tool that may run from
anywhere (the repo root in CI, the project dir from a Makefile target). So the
project root is **discovered**, not assumed:

    1. ``--project-dir`` flag, else ``$ADAF_PROJECT_DIR``         (explicit; must hold dbt_project.yml)
    2. cwd, then each ancestor                                    (walk up for dbt_project.yml)
    3. otherwise fail loud — never guess.

``main()`` resolves it once and stores it on ``PROJECT_ROOT``; every check then
reads ``config.PROJECT_ROOT`` (or takes an explicit ``cwd`` override, so the pure
logic stays unit-testable). Relative ``--manifest``/``--catalog``/``--selectors``
paths are resolved against it in ``main()``.
"""

# Standard Library
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# The dbt project root. A safe default of cwd (matches the legacy behaviour when the
# process already runs in the project); main() overrides it with the discovered root.
PROJECT_ROOT: Path = Path.cwd()

# Env var that overrides discovery (parallels dbt's own --project-dir / DBT_PROJECT_DIR).
PROJECT_DIR_ENV = "ADAF_PROJECT_DIR"

# Git ref the "changed models" detection diffs against (merge-base with HEAD).
# Override per-invocation with --base-ref; CI passes the PR base (e.g. origin/main).
DEFAULT_BASE_REF = "main"

# Default project-relative paths (resolved against PROJECT_ROOT in main()).
DEFAULT_MANIFEST = Path("target") / "manifest.json"
DEFAULT_CATALOG = Path("target") / "catalog.json"
DEFAULT_SELECTORS = Path("selectors.yml")  # dbt hardcodes this filename (never .yaml)
DEFAULT_SDAG_OUTPUT = Path("tmp") / "sdag"
DEFAULT_WORKFLOWS_DIR = Path(".github") / "workflows"  # where `gha create` writes adaf-<product>.yml

# `gha create` clones a canonical skeleton regardless of what product workflows already exist. Absolute
# (package-relative) path: `under_root` passes it through unchanged. Mirrors the sdag assets pattern.
GHA_ASSETS_DIR = Path(__file__).resolve().parent / "gha" / "assets"
DEFAULT_WORKFLOW_TEMPLATE = GHA_ASSETS_DIR / "workflow-template.yml"

# Pathspec for "what is a model file" — kept identical to the Makefile's CHANGED_MODELS.
MODEL_GLOB = "models/*.sql"


def project_root() -> Path:
    """The discovered dbt project root (an accessor over the module global ``PROJECT_ROOT``).

    A function form so call sites read the *current* root even if ``set_project_root`` runs after
    import; several modules call ``config.project_root()`` rather than reaching for the
    ``PROJECT_ROOT`` global directly.
    """
    return PROJECT_ROOT


def resolve_project_root(override: str | os.PathLike | None = None) -> Path:
    """Resolve the dbt project root, failing loud if none can be found.

    ``override`` comes from ``--project-dir``; ``$ADAF_PROJECT_DIR`` is the env fallback;
    otherwise walk up from cwd looking for ``dbt_project.yml``.
    """
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


def set_project_root(override: str | os.PathLike | None = None) -> Path:
    """Discover and record the project root on the module (called once by main())."""
    global PROJECT_ROOT
    PROJECT_ROOT = resolve_project_root(override)
    log.debug("dbt project root: %s", PROJECT_ROOT)
    return PROJECT_ROOT


def under_root(path: Path | None) -> Path | None:
    """Resolve a possibly-relative path arg against PROJECT_ROOT (absolute paths pass through)."""
    if path is None:
        return None
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p
