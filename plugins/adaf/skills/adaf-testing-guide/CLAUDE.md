# adaf-testing-guide — maintainer guide

**Read the ADR log first.** Each ADR carries a **Lens**: a forward-looking rule to apply to the next
decision, so you can answer a new question by reusing recorded reasoning instead of re-deriving it.

This is the maintainer decision lens for the skill. Usage detail lives in [`SKILL.md`](SKILL.md);
the human explainer in [`README.md`](README.md). This file records only *rationale* — never restates
commands or the operating procedure.

## Development contract

This skill is **docs-only** — there is no `scripts/` directory, so there is no `make fix`/`make ci`
code gate. Its CI is the **documentation gates**, all run from the repo root (never `cd`):

```bash
# 1. Spec + governance compliance:
uv run .claude/skills/check-skill/scripts/check.py plugins/adaf/skills/adaf-testing-guide
# 2. Repopulate the README table of contents:
uvx --from md-toc md_toc --in-place --no-list-coherence github --header-levels 4 \
  plugins/adaf/skills/adaf-testing-guide/README.md
# 3. Both diagram gates must exit 0:
bun run .claude/skills/mermaidjs_diagrams/scripts/mermaid_contrast.ts   plugins/adaf/skills/adaf-testing-guide/README.md
bun run .claude/skills/mermaidjs_diagrams/scripts/mermaid_complexity.ts plugins/adaf/skills/adaf-testing-guide/README.md
```

All four must be clean before handoff.

## File map

| File | Role |
|------|------|
| `SKILL.md` | Agent operating manual — trigger frontmatter + the six-step procedure. |
| `README.md` | Human explainer — purpose, quickstart, architecture diagrams, troubleshooting. |
| `CLAUDE.md` | This file — design rationale and ADR log. |
| `references/testing_taxonomy/` | The bundled catalogue (root README + 5 role folders + ~33 vignettes + template). The single source of truth for rule codes and patterns. |

Related, outside the skill dir: `../../.claude-plugin/plugin.json` and `../../.codex-plugin/plugin.json`
(dual manifests over the shared `skills/` tree), and the repo-root `.agents/skills/adaf-testing-guide`
symlink that exposes the skill to Codex + Copilot.

## Architecture principles

- **The catalogue is authoritative.** Never invent rule codes or DAMA dimensions; they exist only if a
  file under `references/testing_taxonomy/` defines them.
- **Advisory, not enforcing.** The skill recommends and explains; it edits a project's files only on
  explicit request, and always surfaces the vignette's *When NOT to use*.
- **Freshness is a first-class step,** not a nicety — see ADR-0002.
- **Brand-agnostic** ([`../../../../.claude/rules/agnostic_examples.md`](../../../../.claude/rules/agnostic_examples.md)):
  examples use generic dbt names (`fct_orders`), never project- or client-specific nouns.

## ADR log

### ADR-0001 — Reference-driven, not CLI-driven
**Status:** Accepted. **Context:** The skill was originally `adaf-taxonomy-gaps`, which shelled out to
the `adaf` CLI to detect/fix gaps. That coupled the skill to an installed binary and a JSON contract,
and made it useless anywhere the CLI wasn't present. **Decision:** Bundle the taxonomy as
`references/` markdown and navigate it directly; drop all CLI invocation. **Consequences:** The skill
runs in any agent with file read + web access; the catalogue travels with it. **Lens:** When a skill's
value is *navigating a knowledge base*, bundle the knowledge and read it — don't shell to a tool that
re-derives what a committed file already states.

### ADR-0002 — Web-grounding is a requirement with loud degradation
**Status:** Accepted. **Context:** Vignette code samples and package recommendations date (e.g.
`dbt_expectations` was flagged unmaintained 2026-05). A skill that emits a dated snippet as if current
is worse than one that admits uncertainty. **Decision:** Step 5 web-grounds syntax against current docs
before any implementation; if web access is absent, the skill proceeds but **announces the guidance is
unverified** and names what to confirm. **Consequences:** Output stays trustworthy across model/doc
drift; offline use is degraded, not silently wrong. **Lens:** A freshness step that cannot run must
announce staleness — never let a degraded environment silently downgrade a requirement (escalators, not
stairs).

### ADR-0003 — Cross-tool compatibility via dual manifest + shared symlink
**Status:** Accepted. **Context:** The same `SKILL.md` is the portable agentskills.io unit, but each
tool scans different locations. **Decision:** Keep `.claude-plugin/plugin.json` for Claude, add
`.codex-plugin/plugin.json` for Codex (both over one `skills/` tree), and expose the skill at
`.agents/skills/` (the one dir Codex *and* Copilot scan; Codex follows symlinks). **Consequences:** One
source tree, three tools, zero content duplication. **Lens:** Skill *content* ports unchanged across
tools; *location and manifest* are the only blockers — solve them with a symlink and a parallel manifest,
never by copying the skill.

### ADR-0004 — No scripts/ directory; doc gates are the CI
**Status:** Accepted. **Context:** The skill does no computation — it reads markdown and the project.
Adding a `scripts/` Makefile `fix`/`ci` loop would be ceremony with nothing to gate. **Decision:** Ship
docs-only; treat `check-skill` + the two mermaid gates + `mdtoc` as the contract. **Consequences:** The
`scripts.md`/`evals.md` code contracts don't apply here. **Lens:** Don't bolt a code contract onto a
docs-only skill — its CI is the documentation gates, and an empty Makefile is a smell, not compliance.

## Extension checklist

- [ ] Change preserves reference-driven operation (no new CLI/binary dependency) — ADR-0001.
- [ ] Any new test guidance points at a **real** vignette/rule code in `references/`.
- [ ] Web-grounding step still present and still degrades loudly — ADR-0002.
- [ ] All four doc gates clean (check-skill, mdtoc, both mermaid gates).
- [ ] Every touched doc ≤ 500 lines; trio (`SKILL`/`README`/`CLAUDE`) stays DRY by role.
- [ ] Examples remain brand-agnostic (no project/client nouns).
- [ ] If a manifest field changes, update **both** `.claude-plugin` and `.codex-plugin` manifests.

## Known gotchas

- **`allowed-tools` must be space-separated** per the agentskills.io spec. Claude tolerates commas;
  the spec and a strict validator do not. Symptom: a spec linter flags the frontmatter.
- **Codex needs `.codex-plugin/plugin.json`; Copilot needs no manifest** — it just scans
  `.agents/skills/`. Symptom: skill loads in Codex-as-plugin but is invisible to a plain repo checkout
  until the `.agents/skills/` symlink exists and is un-ignored in `.gitignore`.
- **The `.agents/skills/` symlink is git-ignored by default** (`.agents/*`); it only commits because of
  an explicit `!`-negation line. Symptom: a fresh clone is missing the skill for Codex/Copilot.
- **Diagram gate fails on same-hue dark strokes.** Use the primary recipe (700-shade fill +
  `stroke:#fff,color:#fff`); a darker-same-hue stroke drops border contrast below 3:1.
