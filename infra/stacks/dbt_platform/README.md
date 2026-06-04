# `dbt_platform` stack

The foundational platform stack: the per-environment **dbt service accounts**,
their **BigQuery IAM** (self + cross-env reads + human developer grants), the
**Workload Identity Federation bindings** that let CI impersonate them, the
**GCS artefact buckets** for dbt's JSON outputs, and the dedicated
**`dbt-dev-elementary`** reporting SA.

It targets three GCP projects (`dbt-dev-jaffleshop`, `dbt-test-jaffleshop`,
`dbt-prod-jaffleshop`) from one set of `*.tf` files via **partial backend
configuration** — switch envs by changing two inputs at `init` / `plan` time.

> **State location:** grandfathered at `prefix = "terraform/state"` (no
> stack-name segment) — it predates the per-stack convention, so its live state
> is never moved. New stacks use `terraform/state/<stack>`; see
> [`../../README.md`](../../README.md) and
> [`docs/arch/adr-0003-stacks-and-modules-layout.md`](../../../docs/arch/adr-0003-stacks-and-modules-layout.md).

```bash
# via the wrapper (adds the gcloud project guardrail + flag wiring)
uv run --directory infra scripts/tf-stack.py plan dbt_platform dev

# or directly from infra/
terraform -chdir=stacks/dbt_platform init  -backend-config=./backends/<env>.config -reconfigure
terraform -chdir=stacks/dbt_platform plan  -var environment=<env>
terraform -chdir=stacks/dbt_platform apply -var environment=<env> -auto-approve
```

For first-time GCP setup (state bucket, deployer SA, WIF per project) see
[`../../bootstrap/`](../../bootstrap/README.md).

## Layout

```
stacks/dbt_platform/
├── backend.tf          # partial gcs backend block (bucket = "", prefix = "")
├── provider.tf         # google provider, project = local.project_id
├── main.tf             # locals (project_id) + data.google_project smoke test
├── dbt.tf              # dbt SAs, BQ IAM, WIF bindings, artefact buckets, elementary SA
├── variables.tf        # var.environment (validated) + var.region
├── dbt-developers.yml  # curated human-developer registry (decoded in dbt.tf)
└── backends/
    ├── dev.config      # bucket = "dbt-dev-jaffleshop-tfstate", prefix = "terraform/state"
    ├── test.config
    └── prod.config
```

## Architecture

```mermaid
flowchart LR
    repo["GitHub repo<br/>neozenith/dbt-gcp-jaffleshop"]:::ingressPrimary
    wf["Workflow<br/>terraform-cicd-stack-dbt_platform.yml"]:::computePrimary
    dev[("dbt-dev-jaffleshop")]:::dataPrimary
    test[("dbt-test-jaffleshop")]:::dataPrimary
    prod[("dbt-prod-jaffleshop")]:::dataPrimary

    repo --> wf
    wf -->|ready PR| dev
    wf -->|push main| test
    wf -->|tag v*| prod

    classDef ingressPrimary fill:#1e40af,stroke:#93c5fd,color:#fff,stroke-width:2px
    classDef computePrimary fill:#5b21b6,stroke:#c4b5fd,color:#fff,stroke-width:2px
    classDef dataPrimary    fill:#115e59,stroke:#5eead4,color:#fff,stroke-width:2px
```

*One GitHub repo drives three GCP projects via the per-stack caller workflow. Each trigger maps to exactly one environment.*

<details>
<summary>📋 Detailed diagram (15 nodes)</summary>

```mermaid
flowchart LR
    subgraph gh["GitHub neozenith/dbt-gcp-jaffleshop"]
        repo["Repository"]:::ingressPrimary
        wf[".github/workflows/<br/>terraform-cicd-stack-dbt_platform.yml<br/>→ terraform-cicd-per-stack.yml"]:::ingressPrimary
        env_d["Env: dev<br/>WIF_PROVIDER, TF_SA"]:::ingressSecondary
        env_t["Env: test<br/>WIF_PROVIDER, TF_SA"]:::ingressSecondary
        env_p["Env: prod<br/>WIF_PROVIDER, TF_SA"]:::ingressSecondary
    end

    subgraph dev_proj["GCP dbt-dev-jaffleshop"]
        dev_wif["WIF Pool +<br/>OIDC Provider"]:::computePrimary
        dev_sa["terraform-deployer SA"]:::computePrimary
        dev_bucket[("tfstate bucket")]:::dataPrimary
    end

    subgraph test_proj["GCP dbt-test-jaffleshop"]
        test_wif["WIF Pool +<br/>OIDC Provider"]:::computePrimary
        test_sa["terraform-deployer SA"]:::computePrimary
        test_bucket[("tfstate bucket")]:::dataPrimary
    end

    subgraph prod_proj["GCP dbt-prod-jaffleshop"]
        prod_wif["WIF Pool +<br/>OIDC Provider"]:::computePrimary
        prod_sa["terraform-deployer SA"]:::computePrimary
        prod_bucket[("tfstate bucket")]:::dataPrimary
    end

    repo --> wf
    wf --> env_d
    wf --> env_t
    wf --> env_p

    env_d --> dev_wif
    dev_wif --> dev_sa
    dev_sa --> dev_bucket

    env_t --> test_wif
    test_wif --> test_sa
    test_sa --> test_bucket

    env_p --> prod_wif
    prod_wif --> prod_sa
    prod_sa --> prod_bucket

    classDef ingressPrimary   fill:#1e40af,stroke:#93c5fd,color:#fff,stroke-width:2px
    classDef ingressSecondary fill:#dbeafe,stroke:#1e40af,color:#1e293b,stroke-width:1px
    classDef computePrimary   fill:#5b21b6,stroke:#c4b5fd,color:#fff,stroke-width:2px
    classDef dataPrimary      fill:#115e59,stroke:#5eead4,color:#fff,stroke-width:2px
    classDef sgBlue fill:#eff6ff,stroke:#1e40af,color:#1e293b
    classDef sgTeal fill:#f0fdfa,stroke:#115e59,color:#1e293b

    class gh sgBlue
    class dev_proj sgTeal
    class test_proj sgTeal
    class prod_proj sgTeal
```

</details>

## CI Routing

How each Git event maps to a job in the reusable workflow. **Plan everywhere**
during draft review; **apply incrementally** as the change earns trust
(dev → test → prod). The per-stack caller fires only when this stack's paths
(`infra/stacks/dbt_platform/**`, `infra/modules/**`, or the workflows/action)
change.

```mermaid
flowchart TD
    push_feat["push to<br/>feature branch"]:::stateSkippedLight
    pr_draft["draft PR<br/>(stack paths modified)"]:::stateWaitingLight
    pr_ready["ready-for-review PR<br/>(stack paths modified)"]:::stateActiveLight
    push_main["push to main<br/>(stack paths modified)"]:::stateActiveLight
    tag["push tag v*"]:::stateActiveLight
    dispatch["workflow_dispatch<br/>(manual)"]:::stateActiveLight

    skip["(no jobs)"]:::stateSkipped
    plan_matrix["plan<br/>matrix dev/test/prod"]:::stateWaiting
    apply_d["apply / dev"]:::stateActive
    apply_t["apply / test"]:::stateActive
    apply_p["apply / prod"]:::stateError

    push_feat --> skip
    pr_draft --> plan_matrix
    pr_ready --> apply_d
    push_main --> apply_t
    tag --> apply_p
    dispatch --> apply_p

    classDef stateActive       fill:#1e40af,stroke:#93c5fd,color:#fff,stroke-width:2px
    classDef stateActiveLight  fill:#dbeafe,stroke:#1e40af,color:#1e293b,stroke-width:1px
    classDef stateWaiting      fill:#92400e,stroke:#fcd34d,color:#fff,stroke-width:2px
    classDef stateWaitingLight fill:#fef3c7,stroke:#92400e,color:#1e293b,stroke-width:1px
    classDef stateError        fill:#991b1b,stroke:#fca5a5,color:#fff,stroke-width:2px
    classDef stateSkipped      fill:#27272a,stroke:#a1a1aa,color:#fff,stroke-width:1px,stroke-dasharray:5 5
    classDef stateSkippedLight fill:#e4e4e7,stroke:#27272a,color:#52525b,stroke-width:1px,stroke-dasharray:5 5
```

*Trigger → job mapping. Red `apply / prod` is the only path that touches
production; it is gated behind tag pushes or explicit manual dispatch.*

## Authentication

Every workflow job authenticates **without long-lived service-account keys** —
it trades a GitHub-signed OIDC token for a short-lived GCP access token via
Workload Identity Federation. The full two-lens model (TF Deployer + DBT
Developer) lives in [`../../AUTH.md`](../../AUTH.md); the build-time view is in
[`../../bootstrap/README.md`](../../bootstrap/README.md).

## Running Terraform Locally

```bash
make -C infra plan-dev          # STACK defaults to dbt_platform
make -C infra apply-dev
make -C infra validate-all      # init + validate against every env's backend
make -C infra ci                # fmt-check + security + validate-backends + gha-check (no cloud)
```

Switching environments in the same checkout is safe — `-reconfigure` on init
discards the cached backend so `dev` state never gets written to `prod`'s bucket.

## Reference

The block below is auto-generated by `make docs` (terraform-docs). Hand-edits
between the markers are overwritten — keep narrative content above this section.

<!-- BEGIN_TF_DOCS -->
<!-- END_TF_DOCS -->
