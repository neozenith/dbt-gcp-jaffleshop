# `adaf` Architecture

How the pieces fit together. For *usage* see [README.md](README.md); for the *why* behind each
decision see the ADR log in [AGENTS.md](AGENTS.md); for the CI workflow graph see
[../../../docs/adaf-ci-cd.md](../../../docs/adaf-ci-cd.md).

## Two independent flows

The **file-scoped gates** (`list`, `sqlfluff`, `deprecations`, `docscov`, `testcov`) all consume one
`Scoped Change Set` — a scope (changed or all) intersected with a named dbt selector. The **`sdag`
viewer** instead walks the data products (named selectors) in `selectors.yml` and renders them.
Change detection is git's job; scope is dbt's.

```mermaid
flowchart TB
    flags["Scope flags<br/>--changed-only (default) / --all"]:::input
    git["git<br/>merge-base + diff + untracked"]:::proc
    dbtls["dbt ls<br/>--selector &lt;name&gt;"]:::proc
    resolved["Scoped Change Set<br/>resolved .sql files"]:::data
    gates["5 file-scoped gates<br/>list / sqlfluff / deprecations / docscov / testcov"]:::gate

    flags --> git
    flags --> dbtls
    git --> resolved
    dbtls --> resolved
    resolved --> gates

    selectors["selectors.yml<br/>named data products"]:::sdagin
    viewer["sdag viewer (viewer.py)<br/>full + super Cytoscape JSON"]:::sdagproc
    generate["sdag generate<br/>write tmp/sdag/"]:::sdagout
    serve["sdag serve<br/>regen + HTTP host"]:::sdagout

    selectors --> viewer
    viewer --> generate
    viewer --> serve

    classDef input fill:#2563eb,stroke:#fff,color:#fff
    classDef proc fill:#7c3aed,stroke:#fff,color:#fff
    classDef data fill:#b45309,stroke:#fff,color:#fff
    classDef gate fill:#047857,stroke:#fff,color:#fff
    classDef sdagin fill:#334155,stroke:#fff,color:#fff
    classDef sdagproc fill:#c2410c,stroke:#fff,color:#fff
    classDef sdagout fill:#0f766e,stroke:#fff,color:#fff
```

*Two independent flows at a glance: the file-scoped gates fold a git diff and a `dbt ls` scope into one resolved `Scoped Change Set` of `.sql` files, while `sdag` walks the named selectors straight into the lineage viewer.*

<details>
<summary>Complete diagram — full selection, gate, and sdag wiring (19 nodes)</summary>

```mermaid
flowchart TB
    subgraph selection["selection — resolve the Scoped Change Set"]
        flags["scope flags<br/>--changed-only | --all<br/>--base-ref main | --selector"]:::input
        mb["git merge-base<br/>base-ref vs HEAD"]:::proc
        diff["git diff<br/>glob models/*.sql"]:::proc
        untracked["untracked files<br/>glob models/*.sql"]:::proc
        changed["changed model files"]:::data
        scope["dbt ls --selector &lt;name&gt;<br/>--output path"]:::proc
        resolve["intersect: changed AND scope<br/>(--all -> scope set only)"]:::data
    end

    subgraph gates["gates — consume the resolved file list"]
        list["list<br/>print files"]:::gate
        sqlfluff["sqlfluff lint<br/>--fix: sqlfluff fix --force"]:::gate
        deprecations["dbt-autofix per folder, dry-run<br/>--fix: apply"]:::gate
        docscov["docscov: read manifest.json<br/>fail models missing description"]:::gate
        testcov["testcov: read manifest.json<br/>fail models with zero tests"]:::gate
    end

    subgraph sdag["sdag — lineage viewer (separate flow)"]
        selectors["selectors.yml<br/>named selectors"]:::sdagin
        skip["skip state:modified selectors"]:::sdagproc
        sdagls["dbt ls --selector NAME<br/>--output json (per product)"]:::sdagproc
        manifest["read manifest.json"]:::data
        viewer["viewer.py<br/>full + super Cytoscape JSON + HTML/JS"]:::sdagproc
        generate["sdag generate<br/>-> tmp/sdag/"]:::sdagout
        serve["sdag serve<br/>regenerate + HTTP host"]:::sdagout
    end

    mb --> diff
    diff --> changed
    untracked --> changed
    flags --> scope
    changed --> resolve
    scope --> resolve
    resolve --> list
    resolve --> sqlfluff
    resolve --> deprecations
    resolve --> docscov
    resolve --> testcov

    selectors --> skip
    skip --> sdagls
    sdagls --> viewer
    manifest --> viewer
    viewer --> generate
    viewer --> serve

    classDef input fill:#2563eb,stroke:#fff,color:#fff
    classDef proc fill:#7c3aed,stroke:#fff,color:#fff
    classDef data fill:#b45309,stroke:#fff,color:#fff
    classDef gate fill:#047857,stroke:#fff,color:#fff
    classDef sdagin fill:#334155,stroke:#fff,color:#fff
    classDef sdagproc fill:#c2410c,stroke:#fff,color:#fff
    classDef sdagout fill:#0f766e,stroke:#fff,color:#fff
```

*The detailed view: git's three-source union (merge-base, diff, untracked) and the `dbt ls` scope call intersect into the resolved set that all five gates read, while `sdag` skips `state:modified` selectors, resolves each product via `dbt ls`, and feeds `viewer.py` to generate or serve the assets.*

</details>

That intersection is the whole point of the gates: of ~1,200 models in the project, only the handful
that are both **changed** and **in your `--selector`** are ever checked.

## Build selection: `adaf ls --flags`

`adaf ls --flags` turns a selector into the dbt `--select`/`--state`/`--defer` flags a `dbt build`
needs. The canonical default seed is `state:modified+ ∩ selector` — the changed models in the
product **plus their in-product descendants** (the `+` is baked into the seed), resolved to concrete
paths because dbt's graph operators can't attach to an intersection. The hop modes instead seed on
the bare change set `state:modified ∩ selector` and let `--upstream`/`--downstream` add `+`/`-`
operators so dbt traverses the lineage out of the product from that seed.
This is what the CI `dbt-build` job runs instead of building the whole product (ADR-0030).

## Findings + the PR comment

Each gate writes its findings as JSON (`--json-out`); the CI matrix uploads them, and `adaf report`
aggregates them into ONE sticky PR comment with two independently-updated sections — `findings`
(posted fast, off the checks) and `build` (the dbt run-results + EDR/sdag links, posted by the build
job). See [AGENTS.md](AGENTS.md) ADR-0028/0029 and the workflow graph in
[../../../docs/adaf-ci-cd.md](../../../docs/adaf-ci-cd.md).

## CI pipeline

The per-product workflow (`adaf-<product>.yml`) is a thin caller of the reusable workflow
(`adaf-reusable.yml`) that holds the parallel job graph (setup → checks ∥ dbt-build → report). Both
the reusable workflow and the `adaf-ci` bootstrap composite action are CLI-owned assets deployed by
`adaf gha init`; `adaf gha create` stamps the per-product caller. The full job graph lives in
[../../../docs/adaf-ci-cd.md](../../../docs/adaf-ci-cd.md).
