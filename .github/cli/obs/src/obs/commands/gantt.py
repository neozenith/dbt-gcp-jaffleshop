"""``obs generate`` / ``obs serve`` — build the Gantt viewer from prod Elementary telemetry.

Thin handlers: extract the window (invocations + run results), build the multi-run bundle,
write the templated viewer. ``serve`` regenerates first so the hosted bundle is always fresh.
"""

# Standard Library
import argparse
import logging

# Local
from obs import config, elementary, gantt, viewer

log = logging.getLogger(__name__)


def _generate(args: argparse.Namespace) -> str:
    """Shared core of generate/serve: query window → bundle → write. Returns the build id."""
    client = elementary.build_client()
    invocations = elementary.fetch_invocations(client, days=args.days, invocation_id=args.invocation_id)
    rows = elementary.fetch_run_results_window(client, days=args.days, invocation_id=args.invocation_id)
    bundle = gantt.build_bundle(invocations, rows, source_label=config.run_results_table(), days=args.days)
    build_id = gantt.write_bundle(args.output, bundle)

    scope = f"invocation {args.invocation_id}" if args.invocation_id else f"last {args.days} days"
    log.info("extracted %d run(s) over %s → %s", bundle["metadata"]["n_runs"], scope, args.output)
    return build_id


def cmd_generate(args: argparse.Namespace) -> int:
    _generate(args)
    log.info("open %s/%s in a browser, or run `obs serve` to host it", args.output, gantt.OBS_HTML)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    _generate(args)  # always regenerate first so the served bundle is fresh
    viewer.serve(args.output, args.port)
    return 0
