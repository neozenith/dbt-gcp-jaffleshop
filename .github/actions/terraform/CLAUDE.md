# `terraform` action — maintainer notes

Read the ADR log below before changing this action; each entry carries a **Lens**
to apply to the next decision.

## The development contract

This is a composite action — there is no engine to run, but a change is not done
until:

```bash
# Lint the action + the workflows that call it (install: brew install actionlint)
actionlint .github/workflows/terraform-cicd-per-stack.yml \
           .github/workflows/terraform-cicd-stack-dbt_platform.yml

# The action body runs the same terraform a human runs — sanity-check it:
terraform -chdir=infra/stacks/dbt_platform init -backend=false
terraform -chdir=infra/stacks/dbt_platform validate

# README diagrams must pass both gates (exit 0)
bun run .claude/skills/mermaidjs_diagrams/scripts/mermaid_contrast.ts   .github/actions/terraform/README.md
bun run .claude/skills/mermaidjs_diagrams/scripts/mermaid_complexity.ts .github/actions/terraform/README.md
```

All commands run from the repo root — never `cd`.

## File map

| File | Role |
|---|---|
| `action.yml` | auth (WIF) → setup-terraform → init → plan/apply, all `-chdir` into `infra/stacks/${stack}`. |
| `README.md` | human usage + architecture diagrams. |
| `CLAUDE.md` | this file — decision log. |

## Architecture principles

Invariants a change must preserve:

- **This action is the ONLY place cloud terraform is invoked.** Reusable/per-stack
  workflows must not inline `terraform init/plan/apply`. If you're adding a
  terraform CLI call to a workflow, it belongs here instead.
- **Orchestration stays in the workflow, never here.** A composite action cannot
  express a job matrix, `environment:`, `needs:`, or `if:` routing — those live
  in `terraform-cicd-per-stack.yml`. Do not try to smuggle env-selection logic in.
- **Per-(env, stack, action).** The action does exactly one env × one stack ×
  one verb. Fan-out is the workflow's matrix, not a loop in here.
- **No long-lived keys.** Auth is always WIF via `google-github-actions/auth`
  with inputs sourced from GitHub Environment `vars` — never a JSON keyfile.
- **apply is atomic.** `apply` does `plan -out=tfplan` then `apply tfplan` so the
  applied changes are exactly the planned ones. Keep these two steps paired.

## ADR log

### ADR-A: Composite action owns all cloud terraform; workflow owns orchestration

- **Status:** Accepted
- **Context:** The prior-art (AWS) reusable workflow inlined `terraform
  init/plan/apply` + credential setup in every job, duplicating it across plan
  and three apply jobs. Porting that verbatim would copy the duplication.
- **Decision:** Centralise auth + init + plan/apply in this composite action;
  the reusable workflow calls it from each job and keeps only matrix / gating /
  routing. The `fmt -check` + backend-validate gate stays in the workflow's
  no-cloud `ci` job (it's repo-wide and runs once, not per env).
- **Consequences:** One place to change how terraform is invoked (version,
  flags, atomic-apply). Workflows shrink to `uses:` + inputs. The cost is a
  layer of indirection — reading a job no longer shows the terraform commands;
  you follow the `uses:` here.
- **Lens:** When a reusable workflow would repeat a cloud CLI invocation across
  jobs, push the invocation into a composite action and leave only matrix /
  environment / routing in the workflow. Duplication of *steps* is the smell;
  duplication of *orchestration* is unavoidable and belongs in the workflow.

### ADR-B: `stack` is an input, defaulting to `dbt_platform`

- **Status:** Accepted
- **Context:** The flat `infra/` stack moved to `infra/stacks/dbt_platform/`
  (see `docs/arch/adr-0003`). The action used to hardcode `-chdir=infra`.
- **Decision:** Add a `stack` input and `-chdir=infra/stacks/${stack}`; default
  it to `dbt_platform` so an omitted input still targets the original stack.
- **Consequences:** One action serves every stack; new stacks need no action
  change, only a per-stack caller workflow forwarding `stack:`.
- **Lens:** When the repo grows a new axis (here: multiple stacks), make it an
  input with a back-compatible default rather than forking the action.

## Extension checklist

A change to this action is done when:

- [ ] `action.yml` inputs all have a `description`; new inputs have a sensible `default` or are truly required.
- [ ] No `terraform` CLI invocation has leaked into a workflow that should live here.
- [ ] `actionlint` is clean on every workflow that `uses:` this action.
- [ ] `README.md` Inputs table + Quickstart match `action.yml`.
- [ ] README Mermaid diagrams pass `mermaid_contrast.ts` AND `mermaid_complexity.ts`.
- [ ] `apply` remains atomic (`plan -out` → `apply tfplan`).

## Known gotchas

- **Empty `vars` ⇒ silent auth failure.** If the calling job omits
  `environment:`, `vars.WIF_PROVIDER`/`vars.TF_SA` resolve to empty strings and
  `auth` fails with a confusing error. The job — not this action — must set
  `environment:`.
- **`id-token: write` is workflow-level.** A composite action can't grant itself
  OIDC permission; the calling workflow must declare it.
- **`-reconfigure` on every init is intentional.** It discards the cached backend
  so switching env in one checkout can't write dev state into prod's bucket.
