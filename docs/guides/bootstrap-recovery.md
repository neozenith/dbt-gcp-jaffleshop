# Recovering from a partial bootstrap

The `bootstrap_*.sh` scripts are idempotent — re-running them is always
safe. This guide covers the failure modes we've actually hit, and what to
do when one of them stops the bootstrap partway through.

## Triage flowchart

```
$ ./infra/bootstrap/bootstrap_project.sh dbt-<env>-jaffleshop <env>

Failure during which step?
├─ "Check billing" / 403 on bucket creation
│  → see "Billing not linked" or "Billing quota exceeded"
├─ Enable APIs hangs or 403
│  → see "API enablement permission denied"
├─ Bucket create fails with 409
│  → bucket name taken globally. Override with TF_STATE_LOCATION (no — that's region;
│    bucket name uniqueness is the issue). See "Bucket name collision".
├─ "Workload Identity Pool" create fails with ALREADY_EXISTS
│  → idempotency bug; report. Workaround: skip with --no-pool flag (not yet supported).
├─ workflow runs but fails at "Failed to retrieve access token"
│  → see "WIF token exchange fails"
```

If the bootstrap aborts on step N, fix the root cause and **re-run the same
command**. Steps 1..N-1 will be idempotent no-ops; step N will retry.

## Billing not linked

**Symptom:** `Check billing` step fails:

```
ERROR: project 'dbt-dev-jaffleshop' has no active billing account.
```

Or — if you somehow bypassed the precheck — GCS bucket creation fails:

```
ERROR: (gcloud.storage.buckets.create) HTTPError 403:
The billing account for the owning project is disabled in state absent.
```

**Cause:** The project has no billing account attached.

**Fix:**

```bash
# 1. List billing accounts you can use
gcloud billing accounts list

# 2. Link the project to one of them
gcloud billing projects link dbt-dev-jaffleshop \
  --billing-account=01E794-FF6B49-4F1419        # <- ACCOUNT_ID from step 1

# 3. Verify
gcloud billing projects describe dbt-dev-jaffleshop
#  billingEnabled: true   <-- you want this

# 4. Re-run bootstrap
./infra/bootstrap/bootstrap_project.sh dbt-dev-jaffleshop dev
```

## Billing quota exceeded

**Symptom:** `gcloud billing projects link` fails:

```
ERROR: (gcloud.billing.projects.link) FAILED_PRECONDITION:
Cloud billing quota exceeded:
https://support.google.com/code/contact/billing_quota_increase
```

**Cause:** GCP caps self-serve billing accounts at **5 linked projects**.
You're hitting the cap.

**Fix (in order of preference):**

1. **Unlink projects you no longer need.**

   ```bash
   gcloud billing projects list --billing-account=<ACCOUNT_ID>
   # Inspect; pick projects that are no longer in use
   gcloud --quiet billing projects unlink <obsolete-project>
   ```

   Unlinking only stops billing for that project — the project itself
   continues to exist and any free-tier resources still work. Re-linking
   later restores everything.

2. **Request a quota increase.** Fill out
   <https://support.google.com/code/contact/billing_quota_increase> asking
   for ≥7 projects per account (3 jaffleshop projects + headroom).
   Turnaround is typically hours to a day.

3. **Use a separate billing account** for the three jaffleshop projects.
   Requires org admin to grant you billing-account-creator.

## API enablement permission denied

**Symptom:** `Enable APIs` step fails:

```
ERROR: (gcloud.services.enable) PERMISSION_DENIED: Caller does not have
required permission to use project ...
```

**Cause:** The active gcloud account lacks `roles/serviceusage.serviceUsageAdmin`
on the project.

**Fix:** Have a project owner grant you that role, or run the bootstrap as
a user that already has `roles/owner`:

```bash
gcloud projects add-iam-policy-binding dbt-dev-jaffleshop \
  --member="user:you@example.com" \
  --role="roles/serviceusage.serviceUsageAdmin"
```

## Bucket name collision

**Symptom:** `Create GCS bucket` step fails:

```
HTTPError 409: Your previous request to create the named bucket
succeeded and you already own it.
```

This is actually OK — the bucket exists from a prior bootstrap and the
script's `describe` check should catch it. If it doesn't, the bucket may
exist in a *different* GCP project (bucket names are globally unique).

**Fix:** Override the bucket name via env var:

```bash
TF_STATE_BUCKET_OVERRIDE=dbt-dev-jaffleshop-tfstate-2 \
  ./infra/bootstrap/bootstrap_project.sh dbt-dev-jaffleshop dev
```

(The script doesn't currently expose this knob — file a follow-up if you
hit this.) The clean fix is to find and delete the unrelated bucket, or
rename the convention in `bootstrap_project.sh`.

## WIF token exchange fails

**Symptom:** The GitHub Actions workflow fails at the auth step:

```
Error: google-github-actions/auth failed with: failed to retrieve
access token: ... Permission denied on resource ...
```

**Possible causes**, in rough order of likelihood:

| Cause | Where to check |
|---|---|
| The OIDC provider's `attribute-condition` doesn't match the running repo | `gcloud iam workload-identity-pools providers describe github-provider --location=global --workload-identity-pool=github-pool` — verify `attributeCondition` includes the right `assertion.repository` value |
| The SA's `workloadIdentityUser` binding is missing or points to the wrong principalSet | `gcloud iam service-accounts get-iam-policy terraform-deployer@<project>.iam.gserviceaccount.com` — verify a `roles/iam.workloadIdentityUser` binding with the right principalSet URI |
| `iamcredentials.googleapis.com` is not enabled on the target project | `gcloud services list --enabled --project=<project> \| grep iamcredentials` |
| The GitHub Environment vars `WIF_PROVIDER` / `TF_SA` are wrong | GitHub UI → Settings → Environments → `<env>` → Variables |

**Fix:** Re-running `bootstrap_project.sh` is the easiest — it re-asserts
every binding and API enablement idempotently. If the issue persists,
check audit logs:

```bash
gcloud logging read 'resource.type="iam_role" OR resource.type="service_account"' \
  --project=<project> --limit=20 --format=json
```

## Re-running selectively

The bootstrap scripts have no `--skip-step` flags — they're designed to be
re-runnable wholesale. If you need surgical replay of one step (e.g. to
re-create the OIDC provider after deleting it manually), the gcloud
commands are listed in `bootstrap_project.sh` and can be copy-pasted out.
