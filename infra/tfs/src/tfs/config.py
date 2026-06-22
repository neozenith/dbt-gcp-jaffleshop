"""Convention + config helpers: the per-env config.yml, the state-prefix rule,
and stack enumeration. Everything here is a pure function of the infra root."""

import logging
from pathlib import Path
from typing import Any

import ruamel.yaml

log = logging.getLogger(__name__)

VALID_ENVS = ["dev", "test", "prod"]
TF_COMMANDS = ["init", "plan", "apply", "force-unlock", "output", "import"]


def load_config(infra_root: Path) -> dict[str, Any]:
    yaml = ruamel.yaml.YAML()
    result: dict[str, Any] = yaml.load((infra_root / "config.yml").read_text())
    return result


def expected_prefix(stack_name: str) -> str:
    """The GCS backend prefix a stack's state MUST live under — one per-stack
    namespace, uniformly."""
    return f"terraform/state/{stack_name}"


def list_stacks(infra_root: Path) -> list[str]:
    stacks_path = infra_root / "stacks"
    if not stacks_path.is_dir():
        return []
    return sorted(s.name for s in stacks_path.iterdir() if s.is_dir())
