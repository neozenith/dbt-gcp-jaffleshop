"""Terraform passthrough commands: init / plan / apply / output / import /
force-unlock. Each is `tfs <command> <stack> <env> [extra...]`.

All terraform invocations run with cwd=infra_root and `-chdir=stacks/<stack>`, so
the infra root resolution (not the process's launch dir) is what anchors paths."""

import logging
import shlex
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from tfs.config import list_stacks
from tfs.errors import TFStackCLIInputError
from tfs.gcp import check_project
from tfs.roots import find_infra_root

log = logging.getLogger(__name__)


def _run_tf(
    command: str,
    stack_name: str,
    environment: str,
    infra_root: Path,
    *,
    lock_id: str = "",
    tf_address: str = "",
    resource_id: str = "",
) -> subprocess.CompletedProcess:
    stack_path = infra_root / "stacks" / stack_name
    if not stack_path.exists():
        log.error("Stack %s does not exist", stack_name)
        sys.exit(1)

    chdir = f"stacks/{stack_name}"
    env_tfvars = stack_path / f"{environment}.tfvars"
    tfvars_flag = f"-var-file={environment}.tfvars" if env_tfvars.exists() else ""

    if command == "init":
        cmd = f"terraform -chdir={chdir} init -backend-config=./backends/{environment}.config -reconfigure"
    elif command == "plan":
        cmd = f"terraform -chdir={chdir} plan -no-color -input=false -var environment={environment} {tfvars_flag}"
    elif command == "apply":
        cmd = f"terraform -chdir={chdir} apply -no-color -input=false -var environment={environment} {tfvars_flag} -auto-approve"
    elif command == "output":
        cmd = f"terraform -chdir={chdir} output -json"
    elif command == "force-unlock":
        cmd = f"terraform -chdir={chdir} force-unlock {lock_id}"
    elif command == "import":
        cmd = f"terraform -chdir={chdir} import -var environment={environment} {tfvars_flag} {shlex.quote(tf_address)} {shlex.quote(resource_id)}"
    else:
        raise TFStackCLIInputError(f"Unsupported terraform command: {command}")

    log.info("Running:\n\n%s\n", cmd)
    capture = command == "output"
    return subprocess.run(shlex.split(cmd), text=True, cwd=infra_root, check=True, capture_output=capture)


def make_tf_handler(command: str):
    """Build the argparse handler for a terraform passthrough subcommand. The
    factory closes over the command name so each leaf gets its own func."""

    def handler(args: Namespace) -> None:
        infra_root = find_infra_root(override=args.infra_root)

        valid_stacks = list_stacks(infra_root)
        if args.stack not in valid_stacks:
            raise TFStackCLIInputError(f"Stack '{args.stack}' does not exist. Must be one of {valid_stacks}")

        check_project(args.env)

        result = _run_tf(
            command,
            args.stack,
            args.env,
            infra_root,
            lock_id=getattr(args, "lock_id", ""),
            tf_address=getattr(args, "address", ""),
            resource_id=getattr(args, "resource_id", ""),
        )
        if command == "output":
            print(result.stdout)

    return handler
