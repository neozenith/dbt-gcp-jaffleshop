"""BigQuery read access to the prod Elementary telemetry — the I/O half of obs.

Everything here talks to BigQuery as the read-scoped ``dbt-dev-elementary`` SA
(see ``config``). Queries return plain ``list[dict]`` of native Python values so the
transform half (``gantt.py``) stays pure and unit-testable without a warehouse.

The single table obs reads today is ``dbt_run_results`` — Elementary's per-node
run telemetry, one row per (model|test|seed|snapshot|source) execution within a
dbt invocation. The four fields the Gantt needs map as:
``thread_id`` · ``unique_id``→node_id · ``execute_started_at``→start · ``execution_time``→duration.
"""

# Standard Library
import logging
from typing import Any

# Third Party
from google.auth import default as google_auth_default
from google.auth.impersonated_credentials import Credentials as ImpersonatedCredentials
from google.cloud import bigquery

# Local
from obs import config

log = logging.getLogger(__name__)


def build_client() -> bigquery.Client:
    """A BigQuery client scoped to read the prod Elementary telemetry.

    Two auth modes (see ``config.impersonate_enabled``):

    * **Impersonation (local default)** — mirrors ``profiles.yml`` ``prod-impersonate``:
      the developer's own ADC is the *source*; BigQuery mints a short-lived token for the
      read-scoped ``dbt-dev-elementary`` SA. No keyfiles; the global gcloud config is untouched.
    * **Direct ADC (CI)** — the runner is already authenticated as ``dbt-prod`` via WIF, so
      use those credentials directly (``OBS_IMPERSONATE=false``).

    Fails loud if ADC is absent or token-minting is denied.
    """
    source_creds, _ = google_auth_default(scopes=config.SCOPES)
    if not config.impersonate_enabled():
        log.debug("BigQuery client: project=%s using ADC directly (impersonation off)", config.prod_project())
        return bigquery.Client(project=config.prod_project(), credentials=source_creds)
    target_creds = ImpersonatedCredentials(
        source_credentials=source_creds,
        target_principal=config.impersonate_sa(),
        target_scopes=config.SCOPES,
        lifetime=600,
    )
    log.debug("BigQuery client: project=%s impersonating=%s", config.prod_project(), config.impersonate_sa())
    return bigquery.Client(project=config.prod_project(), credentials=target_creds)


def fetch_invocations(
    client: bigquery.Client, *, days: int, invocation_id: str | None = None
) -> list[dict[str, Any]]:
    """Run-index rows from ``dbt_invocations`` — one per dbt invocation in the window.

    Carries the metadata the run picker compares: the ``command`` invoked, the configured
    ``threads`` (the real ``--threads`` value), when it ran, and the git sha. Returned newest-first.
    """
    predicate = "invocation_id = @inv" if invocation_id else (
        "created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)"
    )
    params = (
        [bigquery.ScalarQueryParameter("inv", "STRING", invocation_id)]
        if invocation_id
        else [bigquery.ScalarQueryParameter("days", "INT64", days)]
    )
    sql = f"""
        SELECT
          invocation_id,
          command,
          threads,
          run_started_at,
          run_completed_at,
          target_name,
          dbt_version,
          full_refresh,
          git_sha
        FROM `{config.invocations_table()}`
        WHERE {predicate}
        ORDER BY run_started_at DESC
    """
    job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
    rows = [dict(row) for row in job.result()]
    log.debug("fetched %d invocation(s)", len(rows))
    return rows


def fetch_run_results_window(
    client: bigquery.Client, *, days: int, invocation_id: str | None = None
) -> list[dict[str, Any]]:
    """Every executed node across every invocation in the window, as plain dicts.

    Carries ``invocation_id`` so the caller groups rows into per-run Gantts. Only rows with
    a non-null ``execute_started_at`` are returned (a node skipped before execution has no
    interval to draw). Fails loud if the window is empty.
    """
    predicate = "invocation_id = @inv" if invocation_id else (
        "created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)"
    )
    params = (
        [bigquery.ScalarQueryParameter("inv", "STRING", invocation_id)]
        if invocation_id
        else [bigquery.ScalarQueryParameter("days", "INT64", days)]
    )
    sql = f"""
        SELECT
          invocation_id,
          thread_id,
          unique_id                AS node_id,
          name,
          resource_type,
          status,
          message,
          execute_started_at,
          execute_completed_at,
          execution_time           AS duration_secs
        FROM `{config.run_results_table()}`
        WHERE {predicate}
          AND execute_started_at IS NOT NULL
        ORDER BY execute_started_at
    """
    job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
    rows = [dict(row) for row in job.result()]
    if not rows:
        scope = f"invocation {invocation_id}" if invocation_id else f"the last {days} days"
        raise RuntimeError(
            f"no executed nodes found for {scope} in `{config.run_results_table()}` — "
            "is Elementary populated in prod, and is the connecting identity authorised?"
        )
    log.debug("fetched %d run-result rows across the window", len(rows))
    return rows
