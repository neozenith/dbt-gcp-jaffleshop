"""Convention + config helpers: the per-env config.yml, the state-prefix rule,
and stack enumeration. Everything here is a pure function of the infra root."""

import logging
from pathlib import Path

import ruamel.yaml

log = logging.getLogger(__name__)

VALID_ENVS = ["dev", "test", "prod"]
TF_COMMANDS = ["init", "plan", "apply", "force-unlock", "output", "import"]

# Stacks created BEFORE the per-stack state-prefix convention. Their live state
# must never move, so their expected prefix has no <stack_name> segment.
LEGACY_STATE_PREFIX = {"dbt_platform": "terraform/state"}


def load_config(infra_root: Path) -> dict:
    yaml = ruamel.yaml.YAML()
    return yaml.load((infra_root / "config.yml").read_text())


def expected_prefix(stack_name: str) -> str:
    """The GCS backend prefix a stack's state MUST live under."""
    return LEGACY_STATE_PREFIX.get(stack_name, f"terraform/state/{stack_name}")


def list_stacks(infra_root: Path) -> list[str]:
    stacks_path = infra_root / "stacks"
    if not stacks_path.is_dir():
        return []
    return sorted(s.name for s in stacks_path.iterdir() if s.is_dir())
