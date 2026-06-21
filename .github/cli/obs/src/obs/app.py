"""obs CLI — a Typer app over the prod Elementary telemetry.

Two commands today, ``generate`` and ``serve``: both extract prod Elementary run
telemetry into a JSON bundle + a templated Gantt viewer; ``serve`` additionally hosts
it. Business logic lives in ``obs.{elementary,gantt,viewer}`` — this module is *wiring
only*. (Ported from argparse; the migration rationale lives in ``CLAUDE.md``.)

Typer supplies, for free, what hand-rolled wiring otherwise needs: auto-generated
``--help``, ``@app.command`` dispatch, annotation-driven type coercion + validation,
shell completion (``obs --install-completion``), and a ``no_args_is_help`` group.

The ``@app.callback`` runs before any command (logging + repo-root discovery + ``.env``
load) so ``config``'s env-reading functions see a loaded environment before a command
body runs. ``main()`` maps the fail-loud exceptions to a clean ``❌`` line + exit 1 —
see its docstring for how they reach it.
"""

# Standard Library
import logging
import os
from pathlib import Path
from typing import Annotated

# Third Party
import typer
from dotenv import load_dotenv

# Local
from obs import config, elementary, gantt, viewer
from obs.utils.logging_setup import configure_logging

log = logging.getLogger(__name__)

app = typer.Typer(
    name="obs",
    help="dbt observability CLI over the prod Elementary telemetry.",
    no_args_is_help=True,  # bare `obs` prints group help
    add_completion=True,  # free `--install-completion` / `--show-completion`
    pretty_exceptions_enable=False,  # plain traceback for any UNEXPECTED escaping exception (not the 3 caught in main)
)

# ─── Shared option types ──────────────────────────────────────────────────────
# Declared once as Annotated aliases so generate/serve stay DRY.
DaysOpt = Annotated[int, typer.Option(help="Look-back window (days) of runs to extract.")]
InvocationOpt = Annotated[
    str | None,
    typer.Option("--invocation-id", help="Limit extraction to a single dbt invocation_id (default: the whole window)."),
]
NoImpersonateOpt = Annotated[
    bool,
    typer.Option(
        "--no-impersonate", help="Use ADC directly instead of impersonating the read SA (CI runners as dbt-prod)."
    ),
]
OutputOpt = Annotated[
    Path | None,
    typer.Option("-o", "--output", help="Directory for the generated viewer assets (default: <repo>/tmp/obs)."),
]


@app.callback()
def _bootstrap(debug: Annotated[bool, typer.Option(help="Verbose debug logging.")] = False) -> None:
    """Run before every command: configure logging, discover the repo root, load its .env.

    Done here (not per-command) so ``config``'s env-reading functions see the loaded
    ``.env`` before any command resolves a project id / SA / output dir.
    """
    configure_logging(debug=debug)
    config.set_project_root()
    load_dotenv(config.PROJECT_ROOT / ".env")


def _prepare(output: Path | None, *, no_impersonate: bool) -> Path:
    """Resolve the output-dir default and apply the ``--no-impersonate`` sugar.

    ``--no-impersonate`` is sugar for ``OBS_IMPERSONATE=false`` — ``config`` reads the env.
    """
    if no_impersonate:
        os.environ["OBS_IMPERSONATE"] = "false"
    return output or config.default_output_dir()


def _generate(days: int, invocation_id: str | None, output: Path) -> None:
    """Shared core of generate/serve: query the window → bundle → write the templated viewer."""
    client = elementary.build_client()
    invocations = elementary.fetch_invocations(client, days=days, invocation_id=invocation_id)
    rows = elementary.fetch_run_results_window(client, days=days, invocation_id=invocation_id)
    bundle = gantt.build_bundle(invocations, rows, source_label=config.run_results_table(), days=days)
    gantt.write_bundle(output, bundle)

    scope = f"invocation {invocation_id}" if invocation_id else f"last {days} days"
    log.info("extracted %d run(s) over %s → %s", bundle["metadata"]["n_runs"], scope, output)


@app.command()
def generate(
    days: DaysOpt = config.DEFAULT_LOOKBACK_DAYS,
    invocation_id: InvocationOpt = None,
    no_impersonate: NoImpersonateOpt = False,
    output: OutputOpt = None,
) -> None:
    """Extract prod Elementary run telemetry → JSON bundle + Gantt viewer."""
    out = _prepare(output, no_impersonate=no_impersonate)
    _generate(days, invocation_id, out)
    log.info("open %s/%s in a browser, or run `obs serve` to host it", out, gantt.OBS_HTML)


@app.command()
def serve(
    days: DaysOpt = config.DEFAULT_LOOKBACK_DAYS,
    invocation_id: InvocationOpt = None,
    no_impersonate: NoImpersonateOpt = False,
    output: OutputOpt = None,
    port: Annotated[int, typer.Option("-p", "--port", help="HTTP port.")] = 8099,
) -> None:
    """Generate the Gantt viewer, then host it over HTTP."""
    out = _prepare(output, no_impersonate=no_impersonate)
    _generate(days, invocation_id, out)  # always regenerate first so the served bundle is fresh
    viewer.serve(out, port)


def main() -> None:
    """Console-script entrypoint. Maps the fail-loud exceptions to ``❌`` + exit 1.

    Click's standalone mode does not catch non-Click exceptions and Typer re-raises them,
    so these three propagate out of ``app()`` to here (independently of
    ``pretty_exceptions_enable``). They are the expected failure modes: ``RuntimeError``
    (``elementary`` — empty window / auth denied), ``ValueError`` (``gantt`` — empty rows),
    ``FileNotFoundError`` (a missing asset or output path). Each becomes a terse stderr
    line, exit 1, no traceback. Any *other* exception is a bug and escapes with its
    traceback (plain, per ``pretty_exceptions_enable=False``).
    """
    try:
        app()
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        log.error("❌ %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
