# Workload Identity Federation over long-lived service-account keys

**Status:** Accepted
**Date:**   2026-05-26

## Context

GitHub Actions needs to authenticate to GCP to run `terraform plan/apply`
against three projects (`dbt-{dev,test,prod}-jaffleshop`). The choice of
auth mechanism is load-bearing: it sets the trust model for every future
workflow, defines what happens when a credential leaks, and dictates the
operational toil of rotation.

It also determines what GCP-side scaffolding the bootstrap must build (a
Workload Identity Pool + OIDC provider + two IAM bindings, vs. just a
service account with a downloaded key).

## Decision

#### Selected: Workload Identity Federation with SA impersonation

The non-negotiable property is "no long-lived credentials in GitHub
secrets." Both WIF variants meet that bar; the direct-principal variant
is the cleaner endgame, but the SA-impersonation variant has more mature
ecosystem support and a smaller blast-radius surface to debug today. The
extra moving parts (one SA per project, two IAM bindings) are encapsulated
inside `bootstrap_project.sh` and don't add ongoing toil.

The two-gate model is operationally valuable: an attacker who somehow
obtains a valid GitHub OIDC token from another repo still cannot
impersonate this project's deployer SA, because the principalSet binding
restricts impersonation to `attribute.repository ==
'neozenith/dbt-gcp-jaffleshop'`.

We may revisit direct-principal WIF when GCP tooling catches up — a new
ADR will supersede this one if so.

## Consequences

- [+] No long-lived GCP credentials anywhere. Token expiry is ~1h.
- [+] Token leakage is bounded in time and to one workflow's repo claim.
- [+] Per-project SAs give per-env blast-radius isolation — a dev workflow
      compromise cannot reach prod.
- [+] Standardised on the well-trodden `google-github-actions/auth@v3`
      path, so future integrations (Cloud Run deploy, Artifact Registry
      push) follow the same model.
- [-] Bootstrap is more elaborate than `keys create` — additional
      resources to manage per project (one pool, one provider, two
      bindings).
- [-] Debugging failed token exchanges requires reading GCP audit logs;
      errors at the SDK layer are opaque.
- [-] Operationally tied to GitHub Actions OIDC. Migrating CI providers
      later means re-running the bootstrap with a different provider
      config.

## Options

- Long-lived SA key in GitHub Actions secret
- Workload Identity Federation with SA impersonation
- Workload Identity Federation with direct principal-based IAM (no SA
  impersonation)

<details>
<summary>📋 Detailed options outlined</summary>

### Long-lived SA key

#### Pros

- Trivial bootstrap (one `gcloud iam service-accounts keys create`).
- Works with any CI system — no GitHub-specific configuration.
- Mental model is widely understood.

#### Cons

- The key is a *persistent* credential. Anyone with read access to the
  GitHub Actions secret store (or to a leaked `env` dump) gains long-lived
  GCP access.
- Rotation is operational toil — keys must be rotated periodically; the
  old one must remain valid until every consumer is updated.
- Leaks are catastrophic: revoking the key invalidates every running
  workflow globally and leaves no audit trail of which job leaked it.
- GCP itself recommends WIF over keys [in current docs][gcp-docs] and
  labels long-lived keys "high-risk" in Security Health Analytics
  findings.

[gcp-docs]: https://cloud.google.com/iam/docs/keys-create-delete

### WIF with SA impersonation

#### Pros

- No long-lived credentials anywhere. Tokens expire in ~1 hour.
- Two-gate trust model: the OIDC provider's `attribute-condition` *and*
  the SA's `principalSet` binding both restrict access by GitHub repo. A
  misconfiguration on either side fails closed.
- A leaked token is useless after expiry; rotation is automatic per
  workflow run.
- `google-github-actions/auth@v3` and the per-project SA model are well
  documented.
- Compatible with org-wide GitHub Enterprise constraints on repo OIDC.

#### Cons

- Bootstrap is more elaborate (WIF pool, OIDC provider, two IAM bindings
  per project) — see `infra/bootstrap/bootstrap_project.sh`.
- Debugging is harder when something is wrong; failures surface as opaque
  `Permission denied` or `failed to generate access token` errors.
- Two layers of IAM (federation + SA) double the surface for
  misconfiguration.

### WIF with direct principal IAM

#### Pros

- No SA at all — principals from the WIF pool are bound directly to GCP
  resources.
- One less moving part per project (no SA, no
  `iam.serviceAccountTokenCreator` / `iam.workloadIdentityUser` binding).

#### Cons

- Newer pattern; tooling support is uneven. `google-github-actions/auth@v3`
  works but many third-party Terraform modules still assume a SA email.
- Some GCP APIs still expect a service-account principal and reject
  federated principals directly.
- Fewer reference implementations; harder to lean on community examples
  when debugging.

</details>

## References

- [`infra/bootstrap/bootstrap_project.sh`](../../infra/bootstrap/bootstrap_project.sh)
- [`infra/bootstrap/README.md`](../../infra/bootstrap/README.md) §Architecture
- [GCP — Workload Identity Federation for GitHub Actions](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
- [`google-github-actions/auth`](https://github.com/google-github-actions/auth)
