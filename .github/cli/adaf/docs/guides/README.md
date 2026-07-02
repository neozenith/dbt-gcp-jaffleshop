# ADAF Deep Dive Guides

Worked-example walkthroughs for the parts of `adaf` that need more than a `--help` line. Each guide
takes one concept, runs a single example DAG or product through it, and shows the concrete output.

---

## The guides

| Guide | Read it to understand |
|---|---|
| [Github Actions](github-actions.md) | How `adaf gha` generates CI as a shared reusable workflow plus thin per-product callers, and what `init` / `create` / `update` / `analyse` each do. |
| [Super DAG Check Annotations](sdag-check-annotations.md) | How `adaf sdag check` labels every model on a product's edge: **inbound**, **outbound**, **both**, or **inner**. |
| [State Modified Selectors](state-modified-selectors.md) | What each `adaf ls` flag permutation resolves to, scope flag by scope flag, against one example DAG. |
| [State Modified Calculation](state-modified-calculation.md) | How dbt decides a model "changed" — the 7 facets (plus macros) that tip a model from SAME (deferred) to DIFFERENT (rebuilt). |
| [Multiversion & Forward-Compat Testing](multiversion-forward-compat-testing.md) | How the version-matrix suite proves adaf's gates survive every dbt engine (1.11 → 2.0 → Fusion), and how the fixture is migrated to be forward-compatible. |
| [Refactor into a Private Repo](refactor-into-private-repo.md) | How to lift `adaf` into its own private repo, install it org-wide as a `uv` git dependency (with `gh` handling auth), and cut tagged releases automatically from commit messages. |
| [Refactor the Skill into a Plugin Repo](refactor-skill-into-plugin-repo.md) | How to extract `adaf-testing-guide` into a private, cross-tool agent-skills plugin installed via `npx skills@latest add` (with `gh` authenticating the shallow clone). |
