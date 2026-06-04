# `infra/modules/`

Reusable Terraform building blocks, called from one or more `stacks/<stack>/`.

A directory only earns module status once a pattern is consumed by **≥2 callers**
(or is complex enough that isolating + testing it independently pays for itself).
Until then, keep resources inline in the stack — see
[`docs/arch/adr-0003-stacks-and-modules-layout.md`](../../docs/arch/adr-0003-stacks-and-modules-layout.md).

## Layout

Each module is standalone and self-describing:

```
modules/<module_name>/
├── main.tf        # the resources
├── variables.tf   # typed inputs
├── outputs.tf     # values callers consume
├── versions.tf    # required_providers / required_version
└── README.md      # purpose + a terraform-docs Inputs/Outputs block
```

## Levels of abstraction

A useful mental model (borrowed from CDK's construct levels) for deciding *what*
belongs in a module:

- **L1 — primitives.** A single provider resource (`google_storage_bucket`).
  Rarely worth a module on its own.
- **L2 — curated resources.** One logical thing with sane, opinionated defaults
  baked in (a bucket with UBL + PAP + versioning + a lifecycle rule). This is the
  sweet spot for most modules here.
- **L3 — patterns.** A composition of L2 modules that captures a whole
  architectural shape (e.g. "dbt environment" = SA + IAM + artefact bucket).
  Reach for these only once the same composition appears twice.

## Conventions

- Modules are **monorepo-local** — referenced by relative path
  (`source = "../../modules/<name>"`), never a remote registry. Keeps the repo
  self-contained and changes visible in one diff.
- Modules never configure a `provider` or `backend` — those belong to the calling
  stack. A module declares only `required_providers` in `versions.tf`.
- `make docs` runs `terraform-docs` into each module's README between its
  `<!-- BEGIN_TF_DOCS -->` / `<!-- END_TF_DOCS -->` markers.
