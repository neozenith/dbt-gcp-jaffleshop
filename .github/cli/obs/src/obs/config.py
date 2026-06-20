"""Static configuration + project discovery for ``obs``.

``obs`` reads the **prod** Elementary telemetry in BigQuery. The connection
defaults mirror the dbt project's own Makefile so the two stay in lockstep:

| obs setting          | env override (dbt's var)      | default                                              |
|----------------------|-------------------------------|------------------------------------------------------|
| prod project         | ``DBT_BQ_PROJECT_PROD``        | ``dbt-prod-jaffleshop``                              |
| elementary dataset   | ``DBT_BQ_DATASET_ELEMENTARY``  | ``ELEMENTARY``                                       |
| impersonated SA      | ``OBS_IMPERSONATE_SA`` / ``ELEMENTARY_SA`` | ``dbt-dev-elementary@dbt-dev-jaffleshop…``  |

The access path is identical to ``dbt-jaffleshop/profiles.yml``'s
``prod-impersonate`` output: your own gcloud ADC impersonates the read-scoped
``dbt-dev-elementary`` SA — no keyfiles, and your global ADC is never repointed.
You must hold ``serviceAccountTokenCreator`` on that SA (granted via
``infra/stacks/dbt_platform/dbt-developers.yml``).

These are exposed as **functions**, not module constants, so they read the
environment *after* ``main()`` has loaded any ``.env`` — never captured at import.
"""

# Standard Library
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_PROD_PROJECT = "dbt-prod-jaffleshop"
_DEFAULT_ELEMENTARY_DATASET = "ELEMENTARY"
_DEFAULT_IMPERSONATE_SA = "dbt-dev-elementary@dbt-dev-jaffleshop.iam.gserviceaccount.com"
_RUN_RESULTS_TABLE = "dbt_run_results"
_INVOCATIONS_TABLE = "dbt_invocations"

# OAuth scope for both the source ADC and the minted SA token.
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# How far back ``generate`` extracts runs (the viewer shows every run in the window).
DEFAULT_LOOKBACK_DAYS = 30

# The repo root, discovered once by main(); default output lands under <root>/tmp/obs.
PROJECT_ROOT: Path = Path.cwd()


def prod_project() -> str:
    return os.environ.get("DBT_BQ_PROJECT_PROD") or _DEFAULT_PROD_PROJECT


def elementary_dataset() -> str:
    return os.environ.get("DBT_BQ_DATASET_ELEMENTARY") or _DEFAULT_ELEMENTARY_DATASET


def impersonate_sa() -> str:
    return os.environ.get("OBS_IMPERSONATE_SA") or os.environ.get("ELEMENTARY_SA") or _DEFAULT_IMPERSONATE_SA


def run_results_table() -> str:
    """Fully-qualified ``project.dataset.dbt_run_results`` for SQL + the source label."""
    return f"{prod_project()}.{elementary_dataset()}.{_RUN_RESULTS_TABLE}"


def invocations_table() -> str:
    """Fully-qualified ``project.dataset.dbt_invocations`` — the run index source."""
    return f"{prod_project()}.{elementary_dataset()}.{_INVOCATIONS_TABLE}"


def impersonate_enabled() -> bool:
    """Whether to impersonate the read-scoped SA (local default) or use ADC directly.

    In CI the runner is already authenticated as ``dbt-prod`` via WIF (see dbt-docs.yml),
    so impersonation is neither needed nor permitted — set ``OBS_IMPERSONATE=false`` (or
    pass ``--no-impersonate``) there. Locally it defaults on, matching ``profiles.yml``
    ``prod-impersonate``.
    """
    val = os.environ.get("OBS_IMPERSONATE", "true").strip().lower()
    return val not in ("false", "0", "no", "off")


def default_output_dir() -> Path:
    return PROJECT_ROOT / "tmp" / "obs"


def discover_repo_root(override: str | os.PathLike | None = None) -> Path:
    """Resolve the repo root: ``override`` → nearest ``.git``/``dbt_project.yml`` ancestor → cwd.

    Unlike ``adaf`` (which fails loud without a dbt project), ``obs`` reads BigQuery
    and does not strictly need one — the root only anchors ``.env`` loading and the
    default ``tmp/obs`` output dir, so an undiscovered root degrades to cwd, never an error.
    """
    if override:
        return Path(override).expanduser().resolve()
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / ".git").exists() or (d / "dbt_project.yml").exists():
            return d
    return here


def set_project_root(override: str | os.PathLike | None = None) -> Path:
    """Discover and record the repo root on the module (called once by main())."""
    global PROJECT_ROOT
    PROJECT_ROOT = discover_repo_root(override)
    log.debug("repo root: %s", PROJECT_ROOT)
    return PROJECT_ROOT
