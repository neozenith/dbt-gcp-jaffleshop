# `tfs` — Terraform stack lifecycle CLI

The stack lifecycle tool for `infra/` (the stacks + modules layout, GCS backend).
Replaces the old `infra/scripts/tf-stack.py` one-file script with an installable,
multi-module CLI so it can be run as a bare `tfs` from anywhere.

## Install (use anywhere)

```bash
uv tool install 'tfs @ ./infra/tfs'      # from the repo root
# then, from anywhere inside the repo:
tfs validate
tfs plan dbt_platform dev
```

To pick up source changes after editing the tool: `uv tool install --reinstall 'tfs @ ./infra/tfs'`.

## Run without installing (dev / CI)

```bash
uv run --directory infra/tfs tfs validate          # uses this project's env
uv run --frozen --directory infra/tfs tfs gha-check # CI: lockfile-pinned
```

`--directory infra/tfs` sets the working dir inside the package; `tfs` then walks
**up** to find the infra root (`config.yml` + `stacks/`), so discovery still lands
on `infra/`.

## Commands

| Command | What it does |
|---|---|
| `tfs validate` | Check every `stacks/*/backends/*.config` matches the state convention |
| `tfs create <stack>` | Scaffold `stacks/<stack>/` + its per-stack GHA workflow |
| `tfs gha-check` | Verify each stack has a matching CI workflow (and vice versa) |
| `tfs init <stack> <env>` | `terraform init -reconfigure` |
| `tfs plan <stack> <env>` | `terraform plan` |
| `tfs apply <stack> <env>` | `terraform apply -auto-approve` |
| `tfs output <stack> <env>` | `terraform output -json` |
| `tfs import <stack> <env> <addr> <id>` | `terraform import` |
| `tfs force-unlock <stack> <env> <lock_id>` | release a stuck state lock |

Global flags (accepted before or after the subcommand): `--debug` (verbose
logging), `--infra-root <path>` (override discovery; also via `TFS_INFRA_ROOT`).

## How paths are resolved

Two roots are discovered **independently** — the tool never assumes `infra/` and
`.github/` are siblings:

- **infra root** — walk up from cwd for a dir with `config.yml` + `stacks/`
  (override: `--infra-root` / `TFS_INFRA_ROOT`). All stack/module paths hang off this.
- **repo root** — `git rev-parse --show-toplevel`; `.github/workflows/` lives here.

## Layout

```
infra/tfs/
├── pyproject.toml          # name = "tfs", [project.scripts] tfs = "tfs.app:main"
└── src/tfs/
    ├── app.py              # build_parser() + main() — argparse wiring only
    ├── roots.py            # find_infra_root() / find_repo_root()
    ├── config.py           # VALID_ENVS, expected_prefix, load_config, list_stacks
    ├── backends.py         # backend *.config parsing + discovery
    ├── gcp.py              # check_project gcloud guardrail
    ├── errors.py           # typed exceptions
    ├── logging_setup.py    # --debug logging
    ├── commands/           # one handler module per command group
    │   ├── validate.py  create.py  gha.py  terraform.py
    └── templates/          # PACKAGE DATA stamped by `tfs create`
        ├── *.tf  README.md.j2
        ├── backends/base.config.j2
        └── workflows/terraform-cicd-stack-STACKNAME.yml.j2  → .github/workflows/
```

## Tests

```bash
uv run --directory infra/tfs pytest
```
