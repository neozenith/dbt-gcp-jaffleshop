# Refactoring `adaf-testing-guide` into a private agent-skills plugin repo

The testing-guide skill lives at `.agents/skills/adaf-testing-guide`. Like the CLI, it should become
a standalone private repo (`neozenith/adaf-skills`) so every dbt project — and every agent (Claude,
Codex, Copilot) — installs the *same* version via `npx skills@latest add`, rather than vendoring a
copy that drifts.

The skill's own `CLAUDE.md` already designs the target structure (ADR-0003: dual manifest + shared
tree). This guide turns that design into a repo.

---

## 1. The compliant plugin layout

A skill is a portable [agentskills.io](https://agentskills.io) unit: a folder with a `SKILL.md` whose
YAML frontmatter (`name`, `description`, `allowed-tools`) is the contract. **The skill content ports
across tools unchanged** — only the *discovery location and manifest* differ per tool. So the repo
keeps one `skills/` tree and points every tool at it:

```
adaf-skills/                         # private repo root
├── .claude-plugin/
│   └── plugin.json                  # Claude reads this
├── .codex-plugin/
│   └── plugin.json                  # Codex reads this (parallel manifest, same skills/)
├── skills/
│   └── adaf-testing-guide/          # the skill, moved verbatim
│       ├── SKILL.md                 #   frontmatter is the cross-tool contract
│       ├── README.md
│       ├── CLAUDE.md
│       └── references/testing_taxonomy/
└── .agents/
    └── skills/
        └── adaf-testing-guide  ->  ../../skills/adaf-testing-guide   # symlink (Codex + Copilot scan here)
```

Why three pointers over one tree (ADR-0003):

| Tool | Discovers the skill via | Needs |
|---|---|---|
| **Claude Code** | `.claude-plugin/plugin.json` | manifest |
| **Codex** | `.codex-plugin/plugin.json` *and* follows the `.agents/skills/` symlink | manifest + symlink |
| **Copilot** | scans `.agents/skills/` directly | symlink only, no manifest |

Both `plugin.json` manifests describe the *same* `skills/` directory — no content is duplicated.

> **`.gitignore` gotcha (from the skill's CLAUDE.md).** `.agents/*` is git-ignored by default, so the
> symlink won't commit unless you add an explicit negation: `!.agents/skills/adaf-testing-guide`.
> A fresh clone missing the symlink = skill invisible to Codex/Copilot.

### Minimal `plugin.json`

```json
{
  "name": "adaf-skills",
  "description": "ADAF agent skills — dbt data-quality testing guide",
  "version": "0.1.0",
  "skills": ["./skills/adaf-testing-guide"]
}
```

Keep the two manifests identical except for tool-specific fields. The CLAUDE.md extension checklist
already says: **if a manifest field changes, change both.**

### Validate before you publish

The repo carries the same doc gates the skill has today — run them from the repo root:

```bash
uv run .claude/skills/check-skill/scripts/check.py skills/adaf-testing-guide   # agentskills.io spec + governance
```

`allowed-tools` must stay **space-separated** (`Read Grep Glob WebSearch WebFetch`), not comma — a
strict spec validator rejects commas even though Claude tolerates them.

---

## 2. Extract into the private repo

```bash
gh repo create neozenith/adaf-skills --private --description "ADAF agent skills plugin"
gh repo clone neozenith/adaf-skills tmp/adaf-skills

# Move the skill verbatim into skills/ and build the pointers.
mkdir -p tmp/adaf-skills/skills tmp/adaf-skills/.agents/skills
cp -R .agents/skills/adaf-testing-guide tmp/adaf-skills/skills/
ln -s ../../skills/adaf-testing-guide tmp/adaf-skills/.agents/skills/adaf-testing-guide
# ...write the two plugin.json files and the .gitignore negation, then commit + push.
```

---

## 3. Install from the private repo (`npx skills` + `gh` auth)

The in-repo install pattern (seen in the `art-gen` / `art-edit` READMEs) is:

```bash
npx skills@latest add neozenith/adaf-skills --skill adaf-testing-guide
```

### How `gh` authenticates the shallow clone

`npx skills` does **not** call the GitHub API — to fetch `neozenith/adaf-skills` it runs a
`git clone --depth 1` (shallow, for speed). Because it shells out to plain `git`, it inherits the same
credential helper `gh` installs. So the one-time setup is identical to the CLI guide:

```bash
gh auth login          # OAuth your account
gh auth setup-git      # registers `gh auth git-credential` as git's credential helper
```

After that, the shallow clone of the **private** repo authenticates silently with your `gh` token —
no PAT, no SSH key juggling. The skill files land in the consuming project's skills directory
(`.claude/skills/` and/or `.agents/skills/`) and the agent picks them up on next launch.

> **Pin a tag for reproducibility.** If the skills CLI supports a ref (check `npx skills@latest add
> --help`), pin it the same way the CLI guide pins `uv` deps — e.g.
> `npx skills@latest add neozenith/adaf-skills@v0.2.0 --skill adaf-testing-guide`. A pinned skill
> is a reviewable bump, not silent drift.

### Same auth in CI / headless agents

Where there's no interactive `gh login`, fall back to the URL-rewrite lever (identical to the CLI
guide's CI section):

```bash
git config --global url."https://x-access-token:${SKILLS_READ_TOKEN}@github.com/".insteadOf "https://github.com/"
npx skills@latest add neozenith/adaf-skills --skill adaf-testing-guide
```

---

## 4. Versioning the skill

Reuse the CLI guide's release machinery. The skill repo is docs-only (no wheel), so the release job
just needs to tag — `python-semantic-release` still works, driven by Conventional Commits, with the
version living in `plugin.json` (or a `pyproject.toml` shim used only for the version string).

| Commit | Release |
|---|---|
| `fix:` (e.g. corrected a vignette's syntax) | patch |
| `feat:` (e.g. new test vignette) | minor |
| `feat!:` / breaking taxonomy change | major |

Because the skill *content* (rule codes, vignettes) is the product, a `feat:` that adds a vignette is
a real minor release that downstream projects opt into by bumping their pin.

---

## The end state

```mermaid
flowchart LR
  subgraph repo["neozenith/adaf-skills (private)"]
    tree["skills/adaf-testing-guide<br/>(one source tree)"]
    cm[".claude-plugin/plugin.json"]
    xm[".codex-plugin/plugin.json"]
    sym[".agents/skills/ symlink"]
    tree --- cm
    tree --- xm
    tree --- sym
  end
  cm -. "npx skills add (gh auth)" .-> claude["Claude Code"]
  xm -. plugin .-> codex["Codex"]
  sym -. scan .-> copilot["Copilot"]
```

- **One skill tree, three tool pointers** — zero content duplication (ADR-0003).
- **`gh auth setup-git` is the whole auth story** for the private shallow clone, because `npx skills`
  defers to `git`.
- **Conventional commits cut versioned skill releases**, so dbt projects adopt taxonomy updates as a
  visible pin bump.

See also the sibling [`refactor-into-private-repo.md`](refactor-into-private-repo.md) — same `gh` auth
and semantic-release patterns applied to the CLI.
