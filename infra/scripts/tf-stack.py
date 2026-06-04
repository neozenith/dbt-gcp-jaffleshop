# ruff: noqa: E501
# Stack lifecycle helper for the infra/ stacks + modules layout (GCP / GCS backend).
#
# Dependencies (jinja2, ruamel.yaml) are managed by infra/pyproject.toml + uv.lock,
# NOT PEP-723 inline metadata — so `uv run --directory infra` resolves them from the
# project environment (and CI can cache + --frozen the lockfile).
# Run from the infra/ directory (the project rules forbid `cd`, so use uv's
# --directory flag which keeps you at the repo root):
#
#   uv run --directory infra scripts/tf-stack.py <command> [args]
#
# Commands:
#   validate                          Check every stacks/*/backends/*.config matches convention
#   create <stack>                    Scaffold stacks/<stack>/ + its per-stack GHA workflow
#   gha-check                         Verify each stack has a matching CI workflow (and vice versa)
#   init   <stack> <env>              terraform init -reconfigure for that stack/env
#   plan   <stack> <env>              terraform plan
#   apply  <stack> <env>              terraform apply -auto-approve
#   output <stack> <env>             terraform output -json
#   import <stack> <env> <addr> <id>  terraform import
#   force-unlock <stack> <env> <id>   release a stuck state lock

import logging
import shlex
import subprocess
import sys
from pathlib import Path

import jinja2
import ruamel.yaml

log = logging.getLogger(__name__)

log_level = logging.DEBUG if "--debug" in sys.argv else logging.INFO
log_format = "%(asctime)s::%(name)s::%(levelname)s::%(module)s:%(funcName)s:%(lineno)d| %(message)s" if "--debug" in sys.argv else "%(message)s"
log_date_format = "%Y-%m-%d %H:%M:%S"
if "--debug" in sys.argv:
    sys.argv.remove("--debug")  # Safe to remove — we have handled it

logging.basicConfig(level=log_level, format=log_format, datefmt=log_date_format)

VALID_ENVS = ["dev", "test", "prod"]
TF_COMMANDS = ["init", "plan", "apply", "force-unlock", "output", "import"]
VALID_COMMANDS = ["validate", "create", "gha-check"] + TF_COMMANDS

# Stacks created BEFORE the per-stack state-prefix convention. Their live state
# must never move, so their expected prefix has no <stack_name> segment.
LEGACY_STATE_PREFIX = {"dbt_platform": "terraform/state"}


class TerraformBackendConfigError(Exception):
    ...


class TFStackCLIInputError(Exception):
    ...


class TFStackGCPConfigurationError(Exception):
    ...


########################################################################################
# Helpers
########################################################################################

def load_config(working_dir: Path) -> dict:
    yaml = ruamel.yaml.YAML()
    return yaml.load((working_dir / "config.yml").read_text())


def expected_prefix(stack_name: str) -> str:
    """The GCS backend prefix a stack's state MUST live under."""
    return LEGACY_STATE_PREFIX.get(stack_name, f"terraform/state/{stack_name}")


def find_backend_config(working_dir: Path) -> list[Path]:
    return sorted((working_dir / "stacks").glob("**/backends/*.config"))


def parse_backend_config(path: Path) -> dict[str, str]:
    """Parse a terraform `key = "value"` backend config into a dict."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"')
    return out


def stacks(working_dir: Path) -> list[str]:
    stacks_path = working_dir / "stacks"
    if not stacks_path.is_dir():
        return []
    return sorted(s.name for s in stacks_path.iterdir() if s.is_dir())


def check_project(environment: str) -> None:
    """Guardrail: confirm the active gcloud credentials can see the target project.

    The GCP analogue of the AWS account-id check — proves you're authenticated
    against dbt-<env>-jaffleshop before any state-touching terraform call. Hard
    failure (no silent skip): if gcloud can't describe the project, stop.
    """
    project_id = f"dbt-{environment}-jaffleshop"
    try:
        result = subprocess.run(
            ["gcloud", "projects", "describe", project_id, "--format=value(projectId)"],
            text=True, capture_output=True, check=True,
        )
    except FileNotFoundError as e:
        raise TFStackGCPConfigurationError("gcloud CLI not found on PATH — install the Google Cloud SDK") from e
    except subprocess.CalledProcessError as e:
        raise TFStackGCPConfigurationError(
            f"Cannot access project '{project_id}' with the active gcloud credentials.\n"
            f"  Authenticate first (e.g. `gcloud auth login` / ADC impersonation), then retry.\n"
            f"  gcloud said: {e.stderr.strip()}"
        ) from e
    log.debug(f"gcloud sees project: {result.stdout.strip()}")


########################################################################################
# Core CLI commands
########################################################################################

def validate(working_dir: Path) -> None:
    config_paths = find_backend_config(working_dir)
    if not config_paths:
        log.warning("No stacks/*/backends/*.config files found.")
    config = load_config(working_dir)
    env_buckets = {env: cfg["state_bucket"] for env, cfg in config["environments"].items()}

    results: dict[str, list[str]] = {}
    for path in config_paths:
        rel = path.relative_to(working_dir)
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
            log.info(f"✅ {rel} is valid")
        else:
            log.error(f"❌ {rel} is invalid: {results[str(rel)]}")

    total_errors = sum(len(v) for v in results.values())
    log.info(f"Errors: {total_errors}")
    if total_errors > 0:
        sys.exit(1)


def create(stack_name: str, working_dir: Path) -> None:
    yaml = ruamel.yaml.YAML()
    templates_path = working_dir / "scripts" / "templates"
    backend_config_template = templates_path / "backends" / "base.config.j2"
    readme_template = templates_path / "README.md.j2"
    gha_workflow_template = templates_path / ".github" / "workflows" / "terraform-cicd-stack-STACKNAME.yml.j2"

    target_stack_path = working_dir / "stacks" / stack_name
    target_stack_backends_path = target_stack_path / "backends"
    target_gha_workflow_path = working_dir / ".." / ".github" / "workflows" / f"terraform-cicd-stack-{stack_name}.yml"
    base_config = yaml.load((working_dir / "config.yml").read_text())

    if target_stack_path.exists():
        log.info(f"Stack {stack_name} already exists")
        sys.exit(0)

    log.info(f"Creating stack: {stack_name}")
    log.info(f"Creating folder structure in: stacks/{stack_name}")
    target_stack_backends_path.mkdir(parents=True)

    # Copy the static *.tf templates verbatim
    for tf_file in sorted(templates_path.glob("*.tf")):
        target = target_stack_path / tf_file.name
        log.info(f"    Copying scripts/templates/{tf_file.name} --> stacks/{stack_name}/{tf_file.name}")
        target.write_text(tf_file.read_text())

    # Template the per-env backend configs from config.yml
    log.info(f"Creating backend configs for: {stack_name}")
    for environment, env_config in base_config["environments"].items():
        ctx = dict(env_config)
        ctx["environment"] = environment
        ctx["stack_name"] = stack_name
        rendered = jinja2.Template(backend_config_template.read_text(), undefined=jinja2.StrictUndefined).render(**ctx)
        out = target_stack_backends_path / f"{environment}.config"
        log.info(f"    Writing stacks/{stack_name}/backends/{environment}.config")
        out.write_text(rendered)

    # Template the stack README
    log.info(f"Creating README.md for: {stack_name}")
    readme = jinja2.Template(readme_template.read_text(), undefined=jinja2.StrictUndefined).render(stack_name=stack_name)
    (target_stack_path / "README.md").write_text(readme)

    # Template the per-stack GHA workflow at the repo root .github/workflows/
    log.info(f"Creating GHA workflow for: {stack_name}")
    workflow = jinja2.Template(gha_workflow_template.read_text(), undefined=jinja2.StrictUndefined).render(stack_name=stack_name)
    target_gha_workflow_path.write_text(workflow)
    log.info(f"    Writing .github/workflows/terraform-cicd-stack-{stack_name}.yml")

    log.info(f"Stack {stack_name} created successfully ✅")


def gha_check(working_dir: Path) -> None:
    _stacks = set(stacks(working_dir))
    log.info(f"Stacks under stacks/: {sorted(_stacks)}")

    gha_workflows = working_dir / ".." / ".github" / "workflows"
    gha_stacks = {
        f.name.replace("terraform-cicd-stack-", "").replace(".yml", "")
        for f in gha_workflows.glob("terraform-cicd-stack-*.yml")
    }
    log.info(f"Per-stack CI workflows: {sorted(gha_stacks)}")

    missing_workflow = _stacks - gha_stacks
    orphan_workflow = gha_stacks - _stacks

    if missing_workflow or orphan_workflow:
        if missing_workflow:
            log.error(f"❌ Stacks WITHOUT a CI workflow (run `create`, or add one): {sorted(missing_workflow)}")
        if orphan_workflow:
            log.error(f"❌ CI workflows WITHOUT a matching stack: {sorted(orphan_workflow)}")
        sys.exit(1)

    log.info("✅ Every stack has a matching CI workflow.")


def tf(command: str, stack_name: str, environment: str, working_dir: Path,
       lock_id: str = "", tf_address: str = "", resource_id: str = "") -> subprocess.CompletedProcess:
    stack_path = working_dir / "stacks" / stack_name
    if not stack_path.exists():
        log.error(f"Stack {stack_name} does not exist")
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

    log.info(f"Running:\n\n{cmd}\n")
    capture = command == "output"
    return subprocess.run(shlex.split(cmd), text=True, cwd=working_dir, check=True, capture_output=capture)


########################################################################################
# Entrypoint
########################################################################################

def main(working_dir: Path) -> None:
    if len(sys.argv) <= 1 or sys.argv[1] not in VALID_COMMANDS:
        raise TFStackCLIInputError(f"Provide a valid command. Must be one of {VALID_COMMANDS}")

    command = sys.argv[1]

    if command == "validate":
        validate(working_dir)
        return

    if command == "create":
        if len(sys.argv) <= 2:
            raise TFStackCLIInputError("No stack name provided. Usage: tf-stack.py create <stack>")
        create(stack_name=sys.argv[2], working_dir=working_dir)
        return

    if command == "gha-check":
        gha_check(working_dir)
        return

    # Remaining commands are terraform passthroughs: <command> <stack> <env> [...]
    valid_stacks = stacks(working_dir)
    if len(sys.argv) <= 2:
        raise TFStackCLIInputError(f"No stack name provided. Must be one of {valid_stacks}")
    stack_name = sys.argv[2]
    if stack_name not in valid_stacks:
        raise TFStackCLIInputError(f"Stack '{stack_name}' does not exist. Must be one of {valid_stacks}")
    if len(sys.argv) <= 3:
        raise TFStackCLIInputError(f"No environment provided. Must be one of {VALID_ENVS}")
    environment = sys.argv[3]
    if environment not in VALID_ENVS:
        raise TFStackCLIInputError(f"Invalid environment '{environment}'. Must be one of {VALID_ENVS}")

    lock_id = tf_address = resource_id = ""
    if command == "force-unlock":
        if len(sys.argv) <= 4:
            raise TFStackCLIInputError("No lock id provided. Usage: tf-stack.py force-unlock <stack> <env> <lock_id>")
        lock_id = sys.argv[4]
    elif command == "import":
        if len(sys.argv) <= 5:
            raise TFStackCLIInputError("Usage: tf-stack.py import <stack> <env> <tf_address> <resource_id>")
        tf_address = sys.argv[4]
        resource_id = sys.argv[5]

    check_project(environment)

    result = tf(command, stack_name, environment, working_dir=working_dir,
                lock_id=lock_id, tf_address=tf_address, resource_id=resource_id)
    if command == "output":
        print(result.stdout)


if __name__ == "__main__":
    # working_dir is the infra/ root (where config.yml + stacks/ + scripts/ live).
    # `uv run --directory infra ...` sets cwd to infra/, so Path.cwd() is correct.
    try:
        main(working_dir=Path.cwd())
    except Exception as e:
        log.error(f"❌ {e}")
        sys.exit(1)
