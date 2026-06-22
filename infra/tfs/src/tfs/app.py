"""tfs CLI wiring — build_parser() + main() only. No business logic lives here;
handlers come from tfs.commands.*.

Follows the project argparse convention (.claude/rules/python/cli.md): a `_help`
closure as each parser's default func, leaf subcommands overriding it via
set_defaults(func=...), and main() dispatching args.func(args) unconditionally."""

import argparse
import logging
from collections.abc import Callable

from tfs.commands.create import cmd_create
from tfs.commands.gha import cmd_gha_check
from tfs.commands.terraform import make_tf_handler
from tfs.commands.validate import cmd_validate
from tfs.config import VALID_ENVS
from tfs.diagrams.command import cmd_diagram, cmd_diagram_comment
from tfs.logging_setup import configure_logging

log = logging.getLogger(__name__)


def _help(p: argparse.ArgumentParser) -> Callable[[argparse.Namespace], None]:
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

    p_diagram = sub.add_parser(
        "diagram",
        parents=[common],
        help="Render a GCP architecture diagram from terraform state or a delta plan",
    )
    p_diagram.add_argument("stack", help="Stack name")
    p_diagram.add_argument(
        "env",
        nargs="?",
        choices=VALID_ENVS,
        default=None,
        help="Target environment (required unless --readme, which defaults to prod)",
    )
    p_diagram.add_argument(
        "--mode",
        choices=["state", "plan"],
        default="state",
        help="'state' = live infra (default); 'plan' = the delta, coloured by action",
    )
    p_diagram.add_argument(
        "--iam",
        choices=["edges", "nodes"],
        default="edges",
        help="Render IAM grants as role-labelled edges (default) or as boxes",
    )
    p_diagram.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for the .svg/.png (default: <infra-root>/diagrams)",
    )
    p_diagram.add_argument(
        "--readme",
        action="store_true",
        help="Embed the architecture (prod state, SVG-only) in stacks/<stack>/README.md instead",
    )
    p_diagram.add_argument(
        "--check",
        action="store_true",
        help="With --readme: fail if the committed README diagram is stale (don't write)",
    )
    p_diagram.set_defaults(func=cmd_diagram)

    # CI-only companion: link an uploaded diagram artifact into a sticky PR comment.
    # The image files come from `tfs diagram` + actions/upload-artifact; this only
    # posts/updates the comment, so it needs no terraform/cloud access.
    p_comment = sub.add_parser(
        "diagram-comment",
        parents=[common],
        help="Post/update the sticky PR comment linking an uploaded diagram artifact (CI only)",
    )
    p_comment.add_argument("stack", help="Stack name")
    p_comment.add_argument("env", choices=VALID_ENVS, help="Target environment")
    p_comment.add_argument("--mode", choices=["state", "plan"], default="plan", help="Diagram mode label")
    p_comment.add_argument("--png-artifact-id", required=True, help="artifact-id output of the PNG upload-artifact step")
    p_comment.add_argument("--svg-artifact-id", required=True, help="artifact-id output of the SVG upload-artifact step")
    p_comment.set_defaults(func=cmd_diagram_comment)

    # ---- Terraform passthroughs: <command> <stack> <env> [extra...] ----
    def _add_tf(name: str, *, help: str, extra: Callable[[argparse.ArgumentParser], object] | None = None) -> None:
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
