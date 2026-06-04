"""tfs CLI wiring — build_parser() + main() only. No business logic lives here;
handlers come from tfs.commands.*.

Follows the project argparse convention (.claude/rules/python/cli.md): a `_help`
closure as each parser's default func, leaf subcommands overriding it via
set_defaults(func=...), and main() dispatching args.func(args) unconditionally."""

import argparse
import logging

from tfs.commands.create import cmd_create
from tfs.commands.gha import cmd_gha_check
from tfs.commands.terraform import make_tf_handler
from tfs.commands.validate import cmd_validate
from tfs.config import VALID_ENVS
from tfs.logging_setup import configure_logging

log = logging.getLogger(__name__)


def _help(p: argparse.ArgumentParser):
    """Return a handler that prints help for parser p (used as the default func)."""

    def _print_help(_: argparse.Namespace) -> None:
        p.print_help()

    return _print_help


def build_parser() -> argparse.ArgumentParser:
    # Flags every (sub)parser shares, so `--debug` / `--infra-root` work before OR
    # after the subcommand: `tfs --debug plan ...` and `tfs plan ... --debug`.
    #
    # default=SUPPRESS is load-bearing: because these flags live on BOTH the top
    # parser and every subparser (via parents=[common]), a normal default would let
    # the subparser's "unset" value clobber a value already parsed at the top level
    # (`tfs --infra-root X validate`). SUPPRESS means an unset occurrence adds no
    # attribute at all, so the set occurrence always wins. main() then normalises
    # the possibly-absent attributes to concrete defaults.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Verbose debug logging",
    )
    common.add_argument(
        "--infra-root",
        default=argparse.SUPPRESS,
        help="Path to the infra root (a dir with config.yml + stacks/). "
        "Overrides walk-up discovery and the TFS_INFRA_ROOT env var.",
    )

    parser = argparse.ArgumentParser(
        prog="tfs",
        description="Terraform stack lifecycle CLI (stacks + modules layout, GCS backend).",
        parents=[common],
    )
    parser.set_defaults(func=_help(parser))
    sub = parser.add_subparsers(dest="command", required=False)

    # ---- Repo-management commands ----
    p_validate = sub.add_parser(
        "validate",
        parents=[common],
        help="Check every stacks/*/backends/*.config matches the state convention",
    )
    p_validate.set_defaults(func=cmd_validate)

    p_create = sub.add_parser(
        "create",
        parents=[common],
        help="Scaffold stacks/<stack>/ + its per-stack GHA workflow",
    )
    p_create.add_argument("stack", help="Name of the stack to create")
    p_create.set_defaults(func=cmd_create)

    p_gha = sub.add_parser(
        "gha-check",
        parents=[common],
        help="Verify each stack has a matching CI workflow (and vice versa)",
    )
    p_gha.set_defaults(func=cmd_gha_check)

    # ---- Terraform passthroughs: <command> <stack> <env> [extra...] ----
    def _add_tf(name: str, *, help: str, extra=None) -> None:
        p = sub.add_parser(name, parents=[common], help=help)
        p.add_argument("stack", help="Stack name")
        p.add_argument("env", choices=VALID_ENVS, help="Target environment")
        if extra is not None:
            extra(p)
        p.set_defaults(func=make_tf_handler(name))

    _add_tf("init", help="terraform init -reconfigure for <stack>/<env>")
    _add_tf("plan", help="terraform plan for <stack>/<env>")
    _add_tf("apply", help="terraform apply -auto-approve for <stack>/<env>")
    _add_tf("output", help="terraform output -json for <stack>/<env>")
    _add_tf(
        "force-unlock",
        help="Release a stuck state lock for <stack>/<env>",
        extra=lambda p: p.add_argument("lock_id", help="The state lock ID to release"),
    )

    def _import_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("address", help="Terraform resource address (e.g. google_storage_bucket.x)")
        p.add_argument("resource_id", help="Provider resource ID to import")

    _add_tf("import", help="terraform import for <stack>/<env>", extra=_import_args)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    # SUPPRESS leaves these unset when not passed — normalise to concrete defaults
    # so every handler can read args.debug / args.infra_root unconditionally.
    args.debug = getattr(args, "debug", False)
    args.infra_root = getattr(args, "infra_root", None)
    configure_logging(debug=args.debug)
    try:
        args.func(args)
    except Exception as e:  # noqa: BLE001 — top-level guard: log + non-zero exit
        log.error("❌ %s", e)
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
