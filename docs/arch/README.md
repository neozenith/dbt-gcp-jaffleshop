# Architecture Decision Records (ADRs)

We capture architectural and engineering decisions as ADRs so future
contributors can trace *why* a thing was done a particular way and judge
whether the reasoning still holds. This is the pattern from Michael Nygard's
2011 essay [Documenting Architecture Decisions][nygard], adopted broadly
across the open-source ecosystem (notably by [dbt-labs/dbt-adapters][dbt]).

[nygard]: https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
[dbt]: https://github.com/dbt-labs/dbt-adapters/tree/main/docs/arch

## Process

- ADRs live under `docs/arch/`.
- File name: `adr-NNNN-<decision-title>.md` where `NNNN` is a sequential
  zero-padded counter starting at `0001`.
- Use [`templates/default.md`](./templates/default.md) as the starting point.
- Required sections: **Title**, **Context**, **Options**, **Decision**,
  **Consequences**. A `Status` field at the top is used to track lifecycle
  (`Proposed`, `Accepted`, `Superseded by NNNN`, `Deprecated`).
- Once merged, an ADR is **immutable**. Superseding decisions get a new ADR
  that explicitly references the older one; the older ADR's `Status` flips
  to `Superseded by NNNN`.

## When to write an ADR

Write an ADR when a decision is:

- **Architecturally significant** — affects how multiple parts of the system
  fit together (e.g. *auth model*, *deployment topology*, *state location*).
- **Hard to reverse** — the cost of changing it later is high enough that
  future contributors should be able to find the original rationale.
- **Non-obvious from the code** — the code shows what; the ADR explains why,
  and crucially *what alternatives were rejected and why*.

Don't write an ADR for:

- Routine refactors, bug fixes, dependency bumps — use the PR description.
- File-system layout — use the local README.
- Decisions reached and abandoned in the same PR — they leave no artifact to
  explain.

## Index

| ADR | Status | Title |
|---|---|---|
| [0001](./adr-0001-workload-identity-federation.md) | Accepted | Workload Identity Federation over long-lived service-account keys |
| [0002](./adr-0002-single-shared-tf-stack.md) | Superseded by 0003 | Flat `infra/` layout now, migrating to `stacks/` + `modules/` as complexity grows |
| [0003](./adr-0003-stacks-and-modules-layout.md) | Accepted | Migrate the flat `infra/` layout to `stacks/` + `modules/` |
| [0004](./adr-0004-migrate-dbt-platform-state-to-per-stack-prefix.md) | Accepted | Migrate `dbt_platform` Terraform state to the per-stack prefix convention |
| [0005](./adr-0005-adaf-automated-data-assurance-framework.md) | Superseded by 0006 | Consolidate testing-taxonomy tooling into ADAF (Automated Data Assurance Framework) |
| [0006](./adr-0006-retire-adaf-taxonomy-cli-for-agent-skill.md) | Accepted | Retire the ADAF taxonomy CLI; move LLM taxonomy review to the developer-harness agent skill |
