"""`tfs validate` — check every stacks/*/backends/*.config matches the
state-layout convention (bucket per env, prefix per stack)."""

import logging
import sys
from argparse import Namespace

from tfs.backends import find_backend_config, parse_backend_config
from tfs.config import VALID_ENVS, expected_prefix, load_config
from tfs.roots import find_infra_root

log = logging.getLogger(__name__)


def cmd_validate(args: Namespace) -> None:
    infra_root = find_infra_root(override=args.infra_root)
    config_paths = find_backend_config(infra_root)
    if not config_paths:
        log.warning("No stacks/*/backends/*.config files found.")
    config = load_config(infra_root)
    env_buckets = {env: cfg["state_bucket"] for env, cfg in config["environments"].items()}

    results: dict[str, list[str]] = {}
    for path in config_paths:
        rel = path.relative_to(infra_root)
        results[str(rel)] = []
        env_config = path.stem  # dev / test / prod
        stack_name = path.parts[path.parts.index("stacks") + 1]
        parsed = parse_backend_config(path)

        if env_config not in VALID_ENVS:
            results[str(rel)].append(f"invalid environment '{env_config}' (must be one of {VALID_ENVS})")
            continue

        want_bucket = env_buckets.get(env_config, "")
        if parsed.get("bucket") != want_bucket:
            results[str(rel)].append(f"bucket = '{parsed.get('bucket')}', expected '{want_bucket}'")

        want_prefix = expected_prefix(stack_name)
        if parsed.get("prefix") != want_prefix:
            results[str(rel)].append(f"prefix = '{parsed.get('prefix')}', expected '{want_prefix}'")

        if not results[str(rel)]:
            log.info("✅ %s is valid", rel)
        else:
            log.error("❌ %s is invalid: %s", rel, results[str(rel)])

    total_errors = sum(len(v) for v in results.values())
    log.info("Errors: %d", total_errors)
    if total_errors > 0:
        sys.exit(1)
