"""`tfs gha-check` — verify every stack has a matching per-stack CI workflow
(and vice versa). Workflows live at repo_root/.github/workflows/, discovered
independently of the infra root."""

import logging
import sys
from argparse import Namespace

from tfs.config import list_stacks
from tfs.roots import find_infra_root, find_repo_root

log = logging.getLogger(__name__)


def cmd_gha_check(args: Namespace) -> None:
    infra_root = find_infra_root(override=args.infra_root)
    repo_root = find_repo_root(infra_root)

    _stacks = set(list_stacks(infra_root))
    log.info("Stacks under stacks/: %s", sorted(_stacks))

    workflows_dir = repo_root / ".github" / "workflows"
    gha_stacks = {
        f.name.replace("terraform-cicd-stack-", "").replace(".yml", "")
        for f in workflows_dir.glob("terraform-cicd-stack-*.yml")
    }
    log.info("Per-stack CI workflows: %s", sorted(gha_stacks))

    missing_workflow = _stacks - gha_stacks
    orphan_workflow = gha_stacks - _stacks

    if missing_workflow or orphan_workflow:
        if missing_workflow:
            log.error("❌ Stacks WITHOUT a CI workflow (run `tfs create`, or add one): %s", sorted(missing_workflow))
        if orphan_workflow:
            log.error("❌ CI workflows WITHOUT a matching stack: %s", sorted(orphan_workflow))
        sys.exit(1)

    log.info("✅ Every stack has a matching CI workflow.")
