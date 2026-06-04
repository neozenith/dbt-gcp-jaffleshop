# Migrate the flat `infra/` layout to `stacks/` + `modules/`

**Status:** Accepted (supersedes ADR-0002)
**Date:**   2026-06-04

## Context

[ADR-0002](./adr-0002-single-shared-tf-stack.md) chose a flat `infra/` layout
(one implicit stack at the root) and documented the **triggers** that would
force a migration to the stacks + modules pattern: a 2nd deployable stack, a
reusable pattern reaching its 2nd consumer, or a stack growing unwieldy. It also
pre-described the migration as mechanical (file moves + a Makefile `STACK=`
parameter).

We are now adopting that target layout proactively — ahead of the second stack —
because the surrounding scaffolding (a stack-creation CLI, per-stack CI, a
state-prefix convention) is the part that actually makes adding the *next* stack
cheap, and it is far easier to build that scaffolding against one known-good
stack than to retrofit it once several stacks already exist. The prior art is an
established AWS stacks/modules monorepo; we port its **structure** and its
`tf-stack.py` scaffolder, rewritten for GCP (GCS backend, `gcloud` guardrails)
and our existing GitHub-OIDC → WIF composite action.

The one real risk is Terraform state: changing a stack's backend `prefix` orphans
its live state and makes Terraform try to recreate live IAM / SAs / buckets.

## Decision

#### Selected: Adopt `infra/stacks/<stack>/` + `infra/modules/` now, grandfathering the existing stack's state

The model this codifies — modular and extensible:

- **Bootstrap is the bare minimum** for Terraform itself to function: per
  environment, exactly **one GCS state bucket** + a `terraform-deployer` SA + the
  WIF trust CI uses to impersonate it. Nothing application-level. Run directly
  against GCP (`infra/bootstrap/`), never through Terraform.
- **A stack is one cohesive, independently-deployable *definition*.**
  `dbt_platform` is the definition of the dbt platform; it is **not** sharded
  further. A single coherent definition stays a single stack — "deploys
  independently" is achieved by adding *new* stacks, not by fragmenting an
  existing one.
- **One workflow promotes one stack** through dev → test → prod (the per-stack
  caller → the shared reusable workflow).
- **Many stacks, one bucket per env, state namespaced by stack name.** Every new
  stack reuses the bootstrapped per-env bucket and isolates its state at
  `prefix = "terraform/state/<stack>"` (`dbt_platform` grandfathered at
  `terraform/state`).
- **Shared primitives graduate into `modules/`** once a second stack consumes
  them — extracted from real reuse, not anticipated upfront.

Concretely:

- The flat root stack moves verbatim to `infra/stacks/dbt_platform/` (via
  `git mv`, preserving history).
- **Its state is NOT moved.** `dbt_platform` keeps `prefix = "terraform/state"`.
  The GCS backend keys state at `<prefix>/default.tfstate`, so running `init`
  from the new directory with the unchanged backend config points at the *same*
  live object — zero migration, zero risk.
- **New** stacks adopt `prefix = "terraform/state/<stack>"` for per-stack
  isolation. `scripts/tf-stack.py validate` encodes both rules (grandfather list
  + convention) so the boundary is enforced by code, not just prose.
- `scripts/tf-stack.py` (GCP rewrite of the prior-art AWS scaffolder) owns the
  stack lifecycle: `create` (scaffold stack + its CI caller), `validate`,
  `gha-check`, and `terraform` passthroughs gated by a `gcloud projects describe`
  project guardrail.
- CI moves to the per-stack reusable-workflow pattern: a generated per-stack
  caller forwards to a shared reusable workflow, which delegates cloud-touching
  work to the existing `.github/actions/terraform` composite action.

## Consequences

- [+] Adding the next stack is now `make create-stack NAME=<x>` — stack files,
      per-env backends, README, and a wired CI workflow in one command.
- [+] Per-stack state isolation for everything new; blast-radius stays bounded.
- [+] The existing stack's live state is untouched — the migration carried no
      cloud-state operation at all.
- [+] State convention is machine-checked (`tf-stack.py validate` in `make ci`),
      not a documentation footnote that drifts.
- [-] One grandfathered inconsistency: `dbt_platform` sits at
      `terraform/state` while new stacks nest under `terraform/state/<stack>`.
      Captured in `LEGACY_STATE_PREFIX` so it's explicit, not accidental.
- [-] More moving parts than the flat layout (a scaffolder, a reusable workflow,
      templates) — justified now by making stack #2..N cheap, but it is ceremony
      a single stack didn't strictly need.
- [-] Every doc/CI reference to `infra/main.tf`, `infra/backends/...`,
      `infra/dbt.tf` had to be swept to the new stack path (done in this change).

## Options

- Adopt stacks + modules now, grandfathering existing state (**selected**)
- Adopt stacks + modules now AND move existing state to `terraform/state/dbt_platform`
- Stay flat until ADR-0002's triggers fire

<details>
<summary>📋 Detailed options outlined</summary>

### Adopt now, grandfather existing state (selected)

#### Pros

- No cloud-state operation, so no chance of orphaning live IAM/SAs/buckets.
- The scaffolding is built and proven against a real stack before stack #2.

#### Cons

- The grandfathered prefix is a permanent small inconsistency.

### Adopt now AND move existing state to the scoped prefix

#### Pros

- Perfectly uniform: every stack nests under `terraform/state/<stack>`.

#### Cons

- Requires copying the live state object for all three envs (incl. prod) and a
  verified cutover — real risk for purely cosmetic uniformity. Explicitly
  declined by the maintainer for this reason.

### Stay flat until the triggers fire

#### Pros

- Lowest ceremony; matches ADR-0002 as written.

#### Cons

- Defers building the scaffolding to the moment it's most painful (state already
  spread across stacks). Building it now, against one stack, is cheaper.

</details>

## References

- [`docs/arch/adr-0002-single-shared-tf-stack.md`](./adr-0002-single-shared-tf-stack.md) — superseded by this ADR.
- [`infra/README.md`](../../infra/README.md) — the layout as built.
- [`infra/scripts/tf-stack.py`](../../infra/scripts/tf-stack.py) — the scaffolder + state-convention enforcement.
- [`.github/workflows/terraform-cicd-per-stack.yml`](../../.github/workflows/terraform-cicd-per-stack.yml) — the reusable CI workflow.
