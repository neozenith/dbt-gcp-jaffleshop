# CLAUDE.md — maintainer decision lens

This action is now a **thin wrapper** over `adaf review --post`. It owns only the `action.yml`
input/output contract; the engine, rule catalogue, prompt, batching, cost reporting, and
comment-upsert logic were consolidated into the `adaf` CLI.

**Read these instead, in order:**

1. [`docs/arch/adr-0005-adaf-automated-data-assurance-framework.md`](../../../docs/arch/adr-0005-adaf-automated-data-assurance-framework.md)
   — *why* the two engines (deterministic checks + this LLM reviewer) were unified into one tool.
2. [`.github/cli/adaf/CLAUDE.md`](../../cli/adaf/CLAUDE.md) — the engine's development contract, the
   SSoT invariants, and the extension checklist. The historical ADRs for the LLM reviewer
   (GitHub Models / keyless, enum-injection no-drift, batch-under-token-budget, drop-temperature-on-400,
   cost-is-advisory) are preserved as the design rationale `adaf review` still follows.
3. [`docs/guides/adaf.md`](../../../docs/guides/adaf.md) — the consolidated user guide.

## When changing this action

- The `with:` inputs map straight to `adaf review` flags in `action.yml`'s run step. Add an input →
  add the matching flag there and document it in `README.md`. Don't reintroduce engine logic here.
- Anything about *what the review checks or emits* is a catalogue/CLI change — make it in
  `.github/cli/adaf/`, where the tests and the no-drift guards live.
