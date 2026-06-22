"""Terraform passthrough commands: init / plan / apply / output / import /
force-unlock. Each is `tfs <command> <stack> <env> [extra...]`.

All terraform invocations run with cwd=infra_root and `-chdir=stacks/<stack>`, so
the infra root resolution (not the process's launch dir) is what anchors paths."""

import logging
import shlex
import subprocess
from argparse import Namespace
from pathlib import Path

from tfs import _terraform as tf
from tfs.config import list_stacks
from tfs.errors import TFStackCLIInputError
from tfs.gcp import check_project
from tfs.roots import find_infra_root

log = logging.getLogger(__name__)


def build_tf_command(
    command: str,
    stack_name: str,
    environment: str,
    infra_root: Path,
    *,
    lock_id: str = "",
    tf_address: str = "",
    resource_id: str = "",
) -> str:
    """Build the terraform command line for a passthrough subcommand (pure: no exec).

    init/plan/apply come from the shared :mod:`tfs._terraform` driver so `tfs plan`
    and the diagram renderer's plan can never diverge. Raises on an unknown stack or
    an unsupported command so the caller fails loudly."""
    stack_path = infra_root / "stacks" / stack_name
    if not stack_path.exists():
        raise TFStackCLIInputError(f"Stack '{stack_name}' does not exist under {infra_root}/stacks.")

    var_file = tf.tfvars_flag(stack_path, environment)
    chdir = tf.chdir_for(stack_name)

    if command == "init":
        return tf.init_cmd(stack_name, environment)
    if command == "plan":
        return tf.plan_cmd(stack_name, environment, var_file)
    if command == "apply":
        return tf.apply_cmd(stack_name, environment, var_file)
    if command == "output":
        return f"terraform -chdir={chdir} output -json"
    if command == "force-unlock":
        return f"terraform -chdir={chdir} force-unlock {lock_id}"
    if command == "import":
        return (
            f"terraform -chdir={chdir} import -var environment={environment} "
            f"{var_file} {shlex.quote(tf_address)} {shlex.quote(resource_id)}"
        )
    raise TFStackCLIInputError(f"Unsupported terraform command: {command}")


def _run_tf(  # pragma: no cover - terraform subprocess IO seam (cmd construction is build_tf_command)
    command: str,
    stack_name: str,
    environment: str,
    infra_root: Path,
    *,
    lock_id: str = "",
    tf_address: str = "",
    resource_id: str = "",
) -> subprocess.CompletedProcess:
    cmd = build_tf_command(
        command, stack_name, environment, infra_root,
        lock_id=lock_id, tf_address=tf_address, resource_id=resource_id,
    )
    return tf.run(cmd, infra_root, capture=(command == "output"))


def make_tf_handler(command: str):
    """Build the argparse handler for a terraform passthrough subcommand. The
    factory closes over the command name so each leaf gets its own func."""

    def handler(args: Namespace) -> None:  # pragma: no cover - gcloud + terraform IO orchestration
        infra_root = find_infra_root(override=args.infra_root)
        valid_stacks = list_stacks(infra_root)
        if args.stack not in valid_stacks:
            raise TFStackCLIInputError(f"Stack '{args.stack}' does not exist. Must be one of {valid_stacks}")
        check_project(args.env)
        result = _run_tf(
            command, args.stack, args.env, infra_root,
            lock_id=getattr(args, "lock_id", ""),
            tf_address=getattr(args, "address", ""),
            resource_id=getattr(args, "resource_id", ""),
        )
        if command == "output":
            print(result.stdout)

    return handler
