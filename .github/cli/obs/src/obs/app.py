"""obs CLI wiring — build_parser() + main() only. No business logic lives here;
handlers come from obs.commands.*.

Follows the project argparse convention (.claude/rules/python/cli.md): a ``_help``
closure as each parser's default func so an incomplete path prints that group's help
instead of erroring; leaf subcommands override it via ``set_defaults(func=...)``;
``main()`` dispatches ``args.func(args)`` and exits with its returned code.

Command tree (one observability *feature* — the Gantt — to start; more incubate as
sibling subcommands sharing the generate/serve shape)::

    obs
      generate    extract prod Elementary run telemetry → gantt.json + templated viewer
      serve       generate, then host the viewer over HTTP
"""

# Standard Library
import argparse
import logging
import os
from pathlib import Path

# Third Party
from dotenv import load_dotenv

# Local
from obs import config
from obs.commands import gantt as gantt_cmd
from obs.utils.logging_setup import configure_logging

log = logging.getLogger(__name__)


def _help(p: argparse.ArgumentParser):
    """Return a handler that prints help for parser p (used as the default func)."""

    def _print_help(_: argparse.Namespace) -> int:
        p.print_help()
        return 0

    return _print_help


def _add_generate_args(p: argparse.ArgumentParser) -> None:
    """Shared selection + output flags for generate/serve."""
    p.add_argument(
        "--days",
        type=int,
        default=config.DEFAULT_LOOKBACK_DAYS,
        help="Look-back window (days) of runs to extract (default: %(default)s)",
    )
    p.add_argument(
        "--invocation-id",
        dest="invocation_id",
        default=None,
        help="Limit extraction to a single dbt invocation_id (default: every run in the window)",
    )
    p.add_argument(
        "--no-impersonate",
        dest="no_impersonate",
        action="store_true",
        help="Use ADC directly instead of impersonating the read SA (for CI runners already authed as dbt-prod)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Directory for the generated viewer assets (default: <repo>/tmp/obs)",
    )


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help="Verbose debug logging")

    parser = argparse.ArgumentParser(
        prog="obs",
        description="dbt observability CLI over the prod Elementary telemetry.",
        parents=[common],
    )
    parser.set_defaults(func=_help(parser))
    sub = parser.add_subparsers(dest="command", required=False)

    generate = sub.add_parser(
        "generate", parents=[common], help="Extract prod Elementary run telemetry → gantt.json + viewer"
    )
    _add_generate_args(generate)
    generate.set_defaults(func=gantt_cmd.cmd_generate)

    serve = sub.add_parser("serve", parents=[common], help="Generate the Gantt viewer, then host it over HTTP")
    _add_generate_args(serve)
    serve.add_argument("-p", "--port", type=int, default=8099, help="HTTP port (default: %(default)s)")
    serve.set_defaults(func=gantt_cmd.cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.debug = getattr(args, "debug", False)
    configure_logging(debug=args.debug)

    # Discover the repo root, load its .env (prod project id / SA overrides), and resolve the
    # default output dir against it — done after parsing so config functions see the loaded env.
    config.set_project_root()
    load_dotenv(config.PROJECT_ROOT / ".env")
    if getattr(args, "output", None) is None and hasattr(args, "output"):
        args.output = config.default_output_dir()
    # --no-impersonate is sugar for OBS_IMPERSONATE=false (config reads the env).
    if getattr(args, "no_impersonate", False):
        os.environ["OBS_IMPERSONATE"] = "false"

    try:
        rc = args.func(args)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        log.error("❌ %s", exc)
        raise SystemExit(1) from exc
    raise SystemExit(rc or 0)


if __name__ == "__main__":
    main()
