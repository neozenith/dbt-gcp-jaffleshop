# Runbook: move `dbt_platform` state to the per-stack prefix

Move live state from `terraform/state/` → `terraform/state/dbt_platform/` in all
three envs, then delete the `LEGACY_STATE_PREFIX` grandfathering. Reverses the
"never move" call in [ADR-0003](../arch/adr-0003-stacks-and-modules-layout.md).

**Verified state (2026-06-05):** each bucket holds exactly one object,
`terraform/state/default.tfstate`; buckets have 7-day soft-delete (versioning
off). **Critical ordering:** CI `init` uses `-reconfigure` (never migrates), so
the cloud copy MUST exist at the new prefix *before* the code flips — otherwise
Terraform plans a full re-create of live IAM/SAs/buckets.

```bash
# Freeze dbt_platform CI (no merges/tags/dispatch). Phases 1–2 change no files → no CI.
git switch -c chore/dbt-platform-state-migration
BK="tmp/tfstate-backups/dbt-platform-$(date +%F)"; mkdir -p "$BK"
```

## Phase 1 — back up (all envs, read-only)
```bash
for ENV in dev test prod; do B="dbt-$ENV-jaffleshop-tfstate"
  gcloud storage cp "gs://$B/terraform/state/default.tfstate" "$BK/$ENV.tfstate"         # local backup
  gcloud storage cp "gs://$B/terraform/state/default.tfstate" \
                    "gs://$B/terraform/state-backups/dbt_platform-$(date +%F)/default.tfstate"  # in-bucket backup
done
```

## Phase 2 — copy to new prefix + verify (one env at a time: dev→test→prod)
```bash
ENV=dev; B="dbt-$ENV-jaffleshop-tfstate"
gcloud storage cp "gs://$B/terraform/state/default.tfstate" \
                  "gs://$B/terraform/state/dbt_platform/default.tfstate"
# md5 must match:
gcloud storage objects describe "gs://$B/terraform/state/default.tfstate"               --format='value(md5_hash)'
gcloud storage objects describe "gs://$B/terraform/state/dbt_platform/default.tfstate"  --format='value(md5_hash)'
# Terraform reads new object & plans no-op (isolated data dir; needs ADC for $ENV):
TF_DATA_DIR=tmp/tfv/$ENV terraform -chdir=infra/stacks/dbt_platform init -reconfigure \
  -backend-config="bucket=$B" -backend-config="prefix=terraform/state/dbt_platform"
TF_DATA_DIR=tmp/tfv/$ENV terraform -chdir=infra/stacks/dbt_platform plan -input=false -var environment=$ENV
```
Expect **"No changes."** Repeat for `test`, then `prod`. (Skip the local prod
plan if you don't want prod ADC locally — CI re-checks it in Phase 3.)

## Phase 3 — land code (one PR; the triad must move together or `validate` fails)
1. `infra/stacks/dbt_platform/backends/{dev,test,prod}.config`: `prefix` → `terraform/state/dbt_platform`
2. `infra/tfs/src/tfs/config.py`: delete `LEGACY_STATE_PREFIX`; `expected_prefix` → `return f"terraform/state/{stack_name}"`
3. `infra/tfs/tests/test_tfs.py`: `dbt_platform` row → `terraform/state/dbt_platform`
4. Docs: `infra/config.yml`, `infra/stacks/dbt_platform/README.md`, `infra/README.md`, `infra/tfs/README.md`; add `docs/arch/adr-0004-*.md`
```bash
make -C infra ci && uv run --frozen --directory infra/tfs pytest   # local gate, then open PR
```
CI plan/{dev,test,prod} and each apply must be **no-op** (state already at new prefix).

## Phase 4 — decommission legacy (after a soak; backups retained)
```bash
for ENV in dev test prod; do B="dbt-$ENV-jaffleshop-tfstate"
  gcloud storage rm "gs://$B/terraform/state/default.tfstate"   # soft-delete keeps it 7 days
done
```

## Rollback (per phase)
- **1–2:** nothing live changed — `gcloud storage rm` the new object; discard branch.
- **3:** `git revert` the PR — CI re-inits at the still-live old prefix (no-op).
- **4:** restore from `gs://$B/terraform/state-backups/.../default.tfstate` (or soft-delete, 7 days).
