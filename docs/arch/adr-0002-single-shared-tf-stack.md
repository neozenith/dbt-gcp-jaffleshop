# Flat `infra/` Terraform layout now, migrating to `stacks/` + `modules/` as complexity grows

**Status:** Accepted
**Date:**   2026-05-26

## Context

We need a Terraform code layout for a project that will grow. The
long-term target is the **stacks + modules** pattern that separates
deployable units (stacks — each with its own state file) from reusable
building blocks (modules — called from one or more stacks):

```
terraform/
├── bootstrap/                       one-time setup scripts
├── modules/
│   ├── <module_a>/                  one module per reusable pattern
│   │   ├── main.tf
│   │   ├── outputs.tf
│   │   ├── variables.tf
│   │   └── versions.tf
│   └── <module_b>/
├── stacks/
│   ├── <stack_a>/                   one stack per independently-deployed unit
│   │   ├── backend.tf
│   │   ├── backends/{dev,test,prod}.config
│   │   ├── main.tf
│   │   ├── provider.tf
│   │   └── variables.tf
│   └── <stack_b>/
└── scripts/
```

That layout pays off when there are ≥2 stacks (so state isolation between
them is necessary) and ≥1 module reused from ≥2 callers (so the module's
existence is justified by sharing, not anticipation).

**Today this repo has 1 stack and 0 modules.** The smoke-test
`data.google_project` is the entire current footprint; planned future
content includes a BigQuery datasets stack, a Cloud Run / dbt-runner stack,
and an observability stack. The question is *which slice of the target
architecture do we adopt now?*

## Decision

#### Selected: Flat `infra/` layout (single implicit stack at the root) with a documented migration path

We adopt the *minimum* slice today: one set of `.tf` files at `infra/`
plus per-env `infra/backends/<env>.config` files. No `stacks/` directory,
no `modules/` directory. When the conditions for the full layout are met
(see "Triggers" below), the migration is mechanical:

```
infra/                                  infra/
├── backend.tf                          ├── bootstrap/                    (unchanged)
├── backends/{dev,test,prod}.config     ├── modules/                      (new — empty until first module)
├── main.tf                             └── stacks/
├── provider.tf                             └── <stack_name>/             (was the root .tf files)
├── variables.tf                                ├── backend.tf
└── bootstrap/                                  ├── backends/{dev,test,prod}.config
                                                ├── main.tf
                                                ├── provider.tf
                                                └── variables.tf
```

The Makefile gains a `STACK=<name>` variable; `make plan-dev` becomes
`make STACK=<stack_name> plan-dev` (or remains short via a default).

**Triggers for the migration (any one fires it):**

- Adding a 2nd deployable stack — e.g. a separate state for monitoring
  resources that should be deployed independently of the data platform.
- Extracting a reusable pattern into its 2nd consumer — the second time we
  write the same Cloud Storage bucket config or BigQuery dataset wrapper,
  the pattern earns module status.
- A stack growing past ~10 resources and feeling unmanageable as a flat
  set of `.tf` files.

Until one of those fires, the ceremony cost of the multi-stack/module
layout outweighs the structure-for-its-own-sake benefit.

## Consequences

- [+] Lowest possible cognitive overhead for the current 4-file stack.
      Reading order is "open `infra/main.tf`," not "decide which stack to
      open."
- [+] Makefile targets (`plan-dev`, `apply-dev`) don't need a stack
      argument yet; the inner-loop muscle memory stays simple.
- [+] The migration when triggered is mechanical — file moves + one
      Makefile parameter — not a redesign. State migration is handled
      with `terraform state mv` across the new bucket prefixes.
- [+] Diff readability: today's changes are visible in one diff per file,
      not "which stack did this affect?"
- [-] The current layout doesn't match the long-term shape, so
      contributors familiar with the stacks/modules pattern need a
      one-paragraph orientation (this ADR).
- [-] State migration on refactor is non-trivial — moving from one state
      file to per-stack state files requires `terraform state mv` +
      careful cutover (run dev first, validate, then test, then prod).
- [-] Every reference to `infra/main.tf` etc. in docs / READMEs has to
      sweep at migration time. Mitigated by keeping those references in
      a small number of files (`infra/README.md`, `infra/bootstrap/README.md`,
      `infra/Makefile`).
- [-] Adopting the migration *too late* (e.g. waiting until 4 stacks have
      grown) makes the cutover much harder because state has accumulated.
      The "Triggers" list is the early-warning mechanism.

## Options

- Flat `infra/` layout (single implicit stack)
- Stacks-and-modules layout (`infra/stacks/<stack>/` + `infra/modules/<module>/`) from day one
- Per-environment directories (`infra/envs/{dev,test,prod}/`)
- Terraform workspaces on a single shared backend

<details>
<summary>📋 Detailed options outlined</summary>

### Flat `infra/` layout

#### Pros

- Smallest possible structure for a project that today has 1 stack and 0
  modules. Files are where you'd expect.
- Matches the spirit of the long-term layout (partial backend, per-env
  `.config`, `var.environment` dispatch) without the directory ceremony.
- Migration to the multi-stack layout is mechanical when the triggers
  fire.

#### Cons

- Doesn't telegraph the future shape. Contributors familiar with
  stacks/modules layouts ask "where do I put the next thing?"
- One Makefile-level decision (the `STACK=` argument) deferred — a
  one-line change later, but a change nonetheless.

### Stacks-and-modules layout from day one

#### Pros

- Matches the long-term target exactly. No migration burden later.
- Contributors familiar with stacks/modules layouts are immediately
  productive.
- Discourages "just one more file in the root" creep that would make the
  eventual migration harder.

#### Cons

- Adds ceremony to a 4-file project. `infra/stacks/<stack_name>/main.tf`
  is two levels deeper than necessary for current content.
- Pressure to create a second stack or module purely to "use the
  structure" — adopting an architecture before its forcing function
  exists.
- Makefile and CI workflow need the `STACK=` plumbing on day one for a
  feature unused on day one.

### Per-environment directories (`infra/envs/{dev,test,prod}/`)

#### Pros

- Explicit per-env content. Reading `envs/prod/main.tf` shows exactly
  what's in prod.
- Each env can drift independently if needed.

#### Cons

- ~3× duplication of every `.tf` file. A change to a shared resource
  lands in three places; a missed edit silently introduces env drift.
- Doesn't compose with the `stacks/` + `modules/` end state — it's
  *orthogonal* axis splitting (by env) rather than *parallel* axis
  splitting (by deployment unit + by reusable component). Migrating
  later means undoing this layout AND adopting the new one.

### Terraform workspaces

#### Pros

- Built-in Terraform feature; no per-env config files.
- Single backend bucket; workspaces key state by name.

#### Cons

- All env states share one bucket — a misconfigured policy on that bucket
  exposes every env at once. Negates the per-project blast-radius
  isolation we wanted from per-project tfstate buckets.
- HashiCorp's own docs [warn against][hashi-workspace] using workspaces
  for environment separation: "Workspaces are not a way to model the
  difference between development and production environments."
- No way to grant different IAM principals access to different envs —
  the workspace selector is purely a Terraform-side concept.

[hashi-workspace]: https://developer.hashicorp.com/terraform/cli/workspaces#when-not-to-use-workspaces

</details>

## References

- [`infra/README.md`](../../infra/README.md) §Layout — current shape.
- [`infra/Makefile`](../../infra/Makefile) — where the `STACK=` argument
  will be added on migration.
- [HashiCorp — Partial backend configuration](https://developer.hashicorp.com/terraform/language/backend#partial-configuration)
- [HashiCorp — Module composition](https://developer.hashicorp.com/terraform/language/modules/develop/composition)
  — pattern guidance for the `modules/` side once we start extracting.
