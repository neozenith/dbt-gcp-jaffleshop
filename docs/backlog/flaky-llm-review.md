# Backlog: flaky `testing-taxonomy review` (GitHub Models) — handoff

**Status:** the workflow's PR trigger is **disabled** (changed to `workflow_dispatch`-only in the
PR that added this doc — `chore/green-ci-adaf-tests-docs`). Re-enable the `pull_request` trigger
once the retry fix below lands.

**Owner:** unassigned — pick this up in a fresh Claude Code session.

## Symptom

The `testing-taxonomy review` job (LLM review of changed dbt models via GitHub Models) fails
intermittently and, on some runs, **hangs ~14 minutes** before failing. Observed conclusions on
PR #22:

- Run 1: `TimeoutError: The read operation timed out` → `Process completed with exit code 1`.
- Run 2 (re-run): hung ~14 min on the `Run ./.github/actions/dbt-testing-taxonomy-review` step,
  then `failure`.

It is **advisory** (does not block merge), but it is **not OK** — a red check on every PR erodes
signal. All deterministic gates (`adaf check all`, `deploy / test`) are green; this is the only
flaky check.

## Root cause (high confidence)

The HTTP retry loop in the review engine catches only HTTP errors, not network timeouts.

`/.github/cli/adaf/src/adaf/commands/review.py` (the `attempts = 6` loop, ~L152–184):

```python
for attempt in range(attempts):
    req = urllib.request.Request(.../chat/completions, ...)
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:   # L165
            ...
    except urllib.error.HTTPError as e:        # ← ONLY catches HTTP status errors
        if e.code == 429 ...: retry              # rate-limit backoff
        if e.code == 400 and temperature ...: retry
        raise ...
raise RuntimeError("GitHub Models call failed after retries")
```

A slow/unresponsive endpoint raises **`TimeoutError`** (socket read timeout from
`urlopen(timeout=240)`) or **`urllib.error.URLError`** (connection issues). Neither is an
`HTTPError`, so the `except` does **not** catch them — the exception propagates on the **first**
timeout, consuming **zero** of the 6 retries. `https://models.github.ai/inference` (model
`openai/gpt-4.1-mini`) is the flaky dependency.

The ~14-min hang is consistent with `review_models()` batching the changed models into multiple
calls (each up to the 240s timeout); one batch's timeout then aborts the whole job.

## Proposed fix

In `review.py`'s call loop:

1. Add `except (TimeoutError, urllib.error.URLError) as e:` that retries with exponential backoff
   (mirror the 429 path), up to `attempts`. Re-raise only after exhausting retries.
2. Consider lowering the per-call `timeout` (e.g. 90s) and raising `attempts` so a single slow
   response doesn't burn a long wall-clock block before retrying.
3. Optionally reduce batch size in `review_models()` so each call is smaller/faster.
4. Add a top-level guard so a final failure degrades to a "review unavailable — endpoint timeout"
   PR comment + **non-failing** exit (advisory semantics), rather than `exit 1`.

Add a unit test in `.github/cli/adaf/tests/test_review.py` that monkeypatches `urlopen` to raise
`TimeoutError` on the first N attempts and asserts the loop retries then succeeds.

## Affected files

| File | Role |
|---|---|
| `.github/workflows/testing-taxonomy-review.yml` | workflow (PR trigger currently disabled) |
| `.github/actions/dbt-testing-taxonomy-review/action.yml` | thin wrapper → `adaf review --post` |
| `.github/cli/adaf/src/adaf/commands/review.py` | engine: the call/retry loop + `review_models()` batching |
| `.github/cli/adaf/tests/test_review.py` | where the regression test should go |

## Re-enable checklist

- [ ] Land the timeout-retry fix + test in `review.py`.
- [ ] Restore the `pull_request:` trigger in `testing-taxonomy-review.yml` (see the disabled-note there).
- [ ] Confirm a few PR runs are green (or degrade gracefully to a non-failing advisory comment).
