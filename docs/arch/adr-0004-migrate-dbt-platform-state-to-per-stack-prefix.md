# Migrate `dbt_platform` state to the per-stack prefix (drop the grandfather)

**Status:** Accepted (supersedes the state-grandfathering decision in [ADR-0003](./adr-0003-stacks-and-modules-layout.md))
**Date:**   2026-06-05

## Context

[ADR-0003](./adr-0003-stacks-and-modules-layout.md) adopted the
`stacks/` + `modules/` layout and the state convention
`prefix = "terraform/state/<stack>"`. To avoid any cloud-state operation during
that refactor, it **grandfathered** the pre-existing `dbt_platform` stack at the
flat prefix `terraform/state`, encoded as `LEGACY_STATE_PREFIX` in
`infra/tfs/src/tfs/config.py`. ADR-0003 explicitly listed "Adopt now AND move
existing state to `terraform/state/dbt_platform`" as the alternative it declined
— "real risk for purely cosmetic uniformity."

Two things changed the calculus:

- The migration turned out to be **low-risk and fully reversible** when done as
  an explicit, backed-up, server-side object copy with a `plan`-no-op gate per
  env — not the in-place backend swap ADR-0003 implicitly feared.
- The grandfather is a permanent special case carried in code (`expected_prefix`
  branch), docs, and a test. Every future reader of the state convention has to
  learn the exception. Removing it makes the rule uniform and the enforcement a
  single expression.

## Decision

Migrate `dbt_platform`'s live state to `terraform/state/dbt_platform` in all
three environments and delete the grandfathering.

The cutover (executed via
[`docs/runbooks/dbt-platform-state-migration.md`](../runbooks/dbt-platform-state-migration.md)):

- **Back up first, mutate never-first.** Each env's state was copied to a local
  file *and* an in-bucket dated backup prefix before anything else, with md5
  verification across all three copies.
- **Copy, don't swap.** A server-side `gcloud storage cp` placed the state at the
  new prefix while leaving the legacy object untouched. Identity was gated on
  matching md5, then on a `terraform plan` showing **No changes** against the new
  object (25/15/21 resources for dev/test/prod) — proving the copied state still
  maps to live infrastructure.
- **Code follows cloud.** Only once the new-prefix objects existed in every env
  did the backend `prefix` flip in the three `backends/*.config` files. Because
  CI `init` is `-reconfigure` (never `-migrate-state`), doing this in the other
  order would have made Terraform plan a full re-create — the central hazard the
  runbook is built to avoid.
- **`expected_prefix` is now uniform:** `return f"terraform/state/{stack_name}"`.
  `LEGACY_STATE_PREFIX` is deleted.

## Consequences

- [+] One state rule, no exceptions — simpler `tfs validate`, docs, and test.
- [+] Per-stack isolation is now actually universal, not "universal except one".
- [+] The migration proved a repeatable, backed-up state-move runbook for any
      future need.
- [-] A one-time cloud-state operation against prod (mitigated by backups +
      `plan`-no-op gates + 7-day bucket soft-delete).
- [-] The legacy `terraform/state/default.tfstate` objects linger until the
      Phase-4 cleanup; dated backups are retained as the archive.

## Options

- Migrate the state and drop the grandfather (**selected**)
- Keep the grandfather indefinitely (ADR-0003's accepted position)

<details>
<summary>📋 Detailed options outlined</summary>

### Migrate and drop the grandfather (selected)

#### Pros
- Uniform convention; the special case disappears from code, docs, and tests.

#### Cons
- Requires a careful, backed-up state move including prod.

### Keep the grandfather (status quo from ADR-0003)

#### Pros
- Zero cloud-state risk; nothing to do.

#### Cons
- A permanent inconsistency every reader must learn; the enforcement code keeps
  a branch purely to describe one historical stack.

</details>

## References

- [`docs/arch/adr-0003-stacks-and-modules-layout.md`](./adr-0003-stacks-and-modules-layout.md) — adopted the layout + grandfather; this ADR supersedes its state-grandfathering decision.
- [`docs/runbooks/dbt-platform-state-migration.md`](../runbooks/dbt-platform-state-migration.md) — the executed cutover runbook.
- [`infra/tfs/src/tfs/config.py`](../../infra/tfs/src/tfs/config.py) — `expected_prefix`, now uniform.
