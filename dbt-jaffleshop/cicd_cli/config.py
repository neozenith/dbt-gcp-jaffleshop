"""Static configuration and default paths for the cicd-cli.

All relative paths resolve against the directory the CLI is invoked from. The
contract is that this is always the dbt project root (``dbt-jaffleshop/``), because
both supported invocations set the cwd there:

    uv run -m cicd_cli ...                          # cwd already = dbt-jaffleshop
    uv run --directory dbt-jaffleshop -m cicd_cli   # --directory sets cwd

Mirrors the knobs the Makefile exposed (BASE_REF, the ``models/*.sql`` glob) so the
two stay behaviourally identical.
"""

# Standard Library
from pathlib import Path

# The dbt project root. Captured once at import; every supported invocation runs
# with cwd here. Functions that touch git / dbt accept an explicit ``cwd`` override
# so they remain unit-testable regardless of the process cwd.
PROJECT_ROOT = Path.cwd()

# Git ref the "changed models" detection diffs against (merge-base with HEAD).
# Override per-invocation with --base-ref; CI passes the PR base (e.g. origin/main).
DEFAULT_BASE_REF = "main"

# dbt writes the parsed project graph here. The source of truth for doc/test coverage.
DEFAULT_MANIFEST = Path("target") / "manifest.json"

# Pathspec for "what is a model file" — kept identical to the Makefile's CHANGED_MODELS.
MODEL_GLOB = "models/*.sql"
