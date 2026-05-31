# Authentication & Authorization

How identities are established and what they may touch, across the two distinct
principals that operate this project. Both authenticate with **zero long-lived
keyfiles** — every cloud token is short-lived, obtained either by GitHub OIDC →
Workload Identity Federation (machines) or by `gcloud` ADC impersonation (humans).

Two lenses:

- **TF Deployer** — the `terraform-deployer` SA that *provisions* identities and
  IAM (the `infra/` stack). Mediated by `terraform.yml`.
- **DBT Developer** — the `dbt-<env>` SAs (and the humans in
  [`dbt-developers.yml`](./dbt-developers.yml)) that *run dbt* against BigQuery.
  Mediated by `dbt-deploy.yml` for CI and `make deploy-dev` for local work.

The two layers hand off: the TF Deployer must apply an environment *before* the
DBT Developer can authenticate into it — the deployer is what creates the
`dbt-<env>` SA and its WIF/impersonation bindings in the first place.

---

## Lens 1 — TF Deployer

The deployer SA is reached only through GitHub OIDC. A GitHub-signed JWT is
exchanged at the WIF provider (gated on `attribute.repository`), yielding a
federated token that impersonates `terraform-deployer`, which then runs
`plan`/`apply` and provisions everything else.

```mermaid
flowchart LR
    gha["GitHub Actions<br/>terraform.yml"]:::ingress
    oidc["GitHub OIDC<br/>JWT"]:::ingress
    wif["WIF provider<br/>github-pool"]:::compute
    tfsa["terraform-deployer SA<br/>vars.TF_SA"]:::compute
    proj[("dbt-env-jaffleshop")]:::data
    res["provisions<br/>dbt-env SA, BQ IAM,<br/>artefact + tfstate buckets"]:::data

    gha --> oidc
    oidc --> wif
    wif -->|impersonate| tfsa
    tfsa --> proj
    tfsa --> res

    classDef ingress  fill:#1e40af,stroke:#93c5fd,color:#fff,stroke-width:2px
    classDef compute  fill:#5b21b6,stroke:#c4b5fd,color:#fff,stroke-width:2px
    classDef data     fill:#115e59,stroke:#5eead4,color:#fff,stroke-width:2px
```

*One repo → one deployer SA per project → it provisions everything else.* | VCS: low ✅

<details>
<summary>📋 Detailed — token exchange + provisioned resources (13 nodes)</summary>

```mermaid
flowchart TD
    subgraph gh["GitHub  neozenith/dbt-gcp-jaffleshop"]
        wf["Workflow<br/>terraform.yml"]:::ingress
        envd["Env dev<br/>WIF_PROVIDER, TF_SA"]:::ingressL
        envt["Env test<br/>WIF_PROVIDER, TF_SA"]:::ingressL
        envp["Env prod<br/>WIF_PROVIDER, TF_SA"]:::ingressL
    end

    subgraph xchg["Token exchange (per env)"]
        oidc["OIDC JWT<br/>sub, repository, ref"]:::compute
        repochk{"attribute.repository<br/>== repo?"}:::computeL
        sts["GCP STS<br/>federated token"]:::compute
        tfsa["terraform-deployer SA<br/>access token ~1h"]:::compute
    end

    subgraph prov["Provisioned by apply (this env's project)"]
        dbtsa["dbt-env SA"]:::data
        selfiam["self BQ IAM<br/>dataEditor + jobUser"]:::dataL
        xiam["cross-env reader IAM<br/>+ developer BQ read"]:::dataL
        buckets[("artefact + tfstate<br/>buckets")]:::data
        wifb["dbt SA WIF +<br/>impersonation bindings"]:::dataL
    end

    wf --> envd
    wf --> envt
    wf --> envp
    envd -->|OIDC| oidc
    envt -->|OIDC| oidc
    envp -->|OIDC| oidc
    oidc --> repochk
    repochk -->|pass| sts
    sts --> tfsa
    tfsa --> dbtsa
    tfsa --> selfiam
    tfsa --> xiam
    tfsa --> buckets
    tfsa --> wifb

    classDef ingress  fill:#1e40af,stroke:#93c5fd,color:#fff,stroke-width:2px
    classDef ingressL fill:#dbeafe,stroke:#1e40af,color:#1e293b,stroke-width:1px
    classDef compute  fill:#5b21b6,stroke:#c4b5fd,color:#fff,stroke-width:2px
    classDef computeL fill:#ede9fe,stroke:#5b21b6,color:#1e293b,stroke-width:1px
    classDef data     fill:#115e59,stroke:#5eead4,color:#fff,stroke-width:2px
    classDef dataL    fill:#ccfbf1,stroke:#115e59,color:#1e293b,stroke-width:1px
    classDef sgBlue   fill:#eff6ff,stroke:#1e40af,color:#1e293b
    classDef sgViolet fill:#f5f3ff,stroke:#5b21b6,color:#1e293b
    classDef sgTeal   fill:#f0fdfa,stroke:#115e59,color:#1e293b

    class gh sgBlue
    class xchg sgViolet
    class prov sgTeal
```

*Each env's GitHub Environment supplies `WIF_PROVIDER` + `TF_SA`; the repo claim
is verified before STS mints a federated token. One apply provisions the dbt SA,
its IAM (including the developer grants), buckets, and WIF bindings.* | VCS: ~32 ✅

</details>

---

## Lens 2 — DBT Developer

Three authentication paths, one per environment, each gated differently:

- **dev** — *humans only*. A developer listed in `dbt-developers.yml` uses
  `gcloud` ADC to impersonate the `dbt-dev` SA (`make deploy-dev`). No CI path.
- **test** — *PRs only*. `dbt-deploy.yml` federates via WIF where
  `attribute.event_name == pull_request` → `dbt-test` SA.
- **prod** — *releases only*. WIF where `event_name` is `workflow_dispatch`, or
  `push` with an IAM condition restricting the ref to `refs/tags/*` → `dbt-prod` SA.

The dotted edges from `dbt-developers.yml` show the **direct** human BigQuery
read granted in every project (browse/query as yourself) — distinct from the
write path, which always routes through a dbt SA.

```mermaid
flowchart LR
    dev["Human developer<br/>dbt-developers.yml"]:::ingress
    pr["PR (CI)"]:::ingress
    rel["tag v* /<br/>workflow_dispatch"]:::danger

    devsa["dbt-dev SA"]:::compute
    testsa["dbt-test SA"]:::compute
    prodsa["dbt-prod SA"]:::danger

    devbq[("dev BigQuery")]:::data
    testbq[("test BigQuery")]:::data
    prodbq[("prod BigQuery")]:::data

    dev -->|gcloud impersonate| devsa
    devsa --> devbq
    pr -->|WIF event=pull_request| testsa
    testsa --> testbq
    rel -->|WIF event=push/dispatch| prodsa
    prodsa --> prodbq
    dev -.->|direct read| devbq
    dev -.->|direct read| testbq
    dev -.->|direct read| prodbq

    classDef ingress fill:#1e40af,stroke:#93c5fd,color:#fff,stroke-width:2px
    classDef compute fill:#5b21b6,stroke:#c4b5fd,color:#fff,stroke-width:2px
    classDef data    fill:#115e59,stroke:#5eead4,color:#fff,stroke-width:2px
    classDef danger  fill:#991b1b,stroke:#fca5a5,color:#fff,stroke-width:2px
```

*dev = human-impersonated, test = PR-triggered, prod = release-gated (red).
Humans also get direct read into all three.* | VCS: ~14 ✅

<details>
<summary>📋 Detailed — env vars, WIF gating, slices, cross-env reads (12 nodes)</summary>

```mermaid
flowchart TD
    subgraph human["Local developer (humans-only)"]
        reg["dbt-developers.yml<br/>developers + groups"]:::ingress
        adc["gcloud ADC<br/>impersonate dbt-dev"]:::ingressL
        mk["make deploy-dev<br/>DBT_TARGET=dev"]:::ingressL
    end

    subgraph ci["GitHub Actions  dbt-deploy.yml"]
        prj["job deploy-test<br/>event=pull_request"]:::ingress
        prodj["job deploy-prod<br/>tag v* / dispatch"]:::danger
        wifp["WIF github-pool<br/>attribute.event_name"]:::computeL
    end

    subgraph sas["dbt service accounts"]
        devsa["dbt-dev SA<br/>tokenCreator: developers"]:::compute
        testsa["dbt-test SA<br/>WIF: pull_request"]:::compute
        prodsa["dbt-prod SA<br/>WIF: dispatch + tag-push"]:::danger
    end

    subgraph bq["BigQuery per project"]
        devbq[("dbt-dev<br/>RW + git-branch slice")]:::data
        testbq[("dbt-test<br/>PRn_RUNid__ slice")]:::data
        prodbq[("dbt-prod<br/>no slice")]:::data
    end

    reg --> adc
    adc --> mk
    mk -->|impersonate| devsa
    prj --> wifp
    prodj --> wifp
    wifp -->|event=pull_request| testsa
    wifp -->|event=push/dispatch| prodsa

    devsa -->|dataEditor| devbq
    devsa -.->|cross-env read| testbq
    devsa -.->|cross-env read| prodbq
    testsa -->|dataEditor| testbq
    testsa -.->|cross-env read| prodbq
    prodsa -->|dataEditor| prodbq

    reg -.->|direct read| devbq
    reg -.->|direct read| testbq
    reg -.->|direct read| prodbq

    classDef ingress  fill:#1e40af,stroke:#93c5fd,color:#fff,stroke-width:2px
    classDef ingressL fill:#dbeafe,stroke:#1e40af,color:#1e293b,stroke-width:1px
    classDef compute  fill:#5b21b6,stroke:#c4b5fd,color:#fff,stroke-width:2px
    classDef computeL fill:#ede9fe,stroke:#5b21b6,color:#1e293b,stroke-width:1px
    classDef data     fill:#115e59,stroke:#5eead4,color:#fff,stroke-width:2px
    classDef danger   fill:#991b1b,stroke:#fca5a5,color:#fff,stroke-width:2px
    classDef sgBlue   fill:#eff6ff,stroke:#1e40af,color:#1e293b
    classDef sgViolet fill:#f5f3ff,stroke:#5b21b6,color:#1e293b
    classDef sgTeal   fill:#f0fdfa,stroke:#115e59,color:#1e293b
    classDef sgRed    fill:#fef2f2,stroke:#991b1b,color:#1e293b

    class human sgBlue
    class ci sgRed
    class sas sgViolet
    class bq sgTeal
```

*Solid = read/write via a dbt SA; dotted = read-only. Cross-env reads (dev→test,
dev→prod, test→prod) come from the `cross_env_readers` map; the three `reg` dotted
edges are the new direct human grants from `dbt-developers.yml`. Non-prod datasets
carry an isolation slice (branch name / `PRn_RUNid__`); prod has none.* | VCS: ~32 ✅

</details>

---

## Why no keyfiles anywhere

Both lenses fail **closed** if either side of the trust is misconfigured:

| Path | GitHub-side gate | GCP-side gate |
|------|------------------|---------------|
| TF Deployer | `terraform.yml` env + `id-token: write` | WIF `attribute.repository` condition + `terraform-deployer` `workloadIdentityUser` binding |
| dbt test | `deploy-test` `if: event_name == pull_request` | `dbt-test` SA `workloadIdentityUser` on `attribute.event_name/pull_request` |
| dbt prod | `deploy-prod` `if: tag-push OR dispatch` | `dbt-prod` SA bindings on `workflow_dispatch` + `push` (IAM condition: `ref` startsWith `refs/tags/`) |
| dbt dev (human) | — | `dbt-dev` SA `serviceAccountTokenCreator` granted to `dbt-developers.yml` members |

The workflow `if:` conditions are belt-and-suspenders — even if one misfired, the
WIF binding itself matches a single `event_name`, so the wrong trigger cannot
impersonate the wrong SA.
