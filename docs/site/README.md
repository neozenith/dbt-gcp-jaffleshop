# Guides site (MkDocs)

A self-contained `uv` subproject that renders the dbt **testing-taxonomy** guide
(`docs/guides/testing_taxonomy/`) as a [MkDocs Material](https://squidfunk.github.io/mkdocs-material/)
static site.

It is published as a **sibling artefact** of the dbt docs on GitHub Pages, mounted
at `/guides/` — see the `Build guides site` step in
[`.github/workflows/dbt-docs.yml`](../../.github/workflows/dbt-docs.yml), which stages
the build into `_site/guides/` alongside `index.html`, `sdag.html`, and
`elementary_report.html`.

## Why a separate subproject

The content (`../guides/testing_taxonomy/`) is authored to render natively on GitHub.
This subproject only adds the *presentation* layer (theme, nav, search, client-side
Mermaid) and keeps its dependency closure (`mkdocs-material`) isolated from the dbt
and `adaf` environments. `docs_dir` points up-and-over at the shared content, so the
markdown stays the single source of truth — there is no copy step.

## Commands

Run from the **repo root** (per the project's working-directory rules — never `cd`):

```bash
# Build to tmp/guides-site/ (gitignored)
uv run --directory docs/site mkdocs build

# Live-reload preview on http://127.0.0.1:8000/
uv run --directory docs/site mkdocs serve
```

Or via the root `Makefile`:

```bash
make guides-build   # one-shot build
make guides-serve   # live preview
```

## Layout

| Path | Purpose |
|------|---------|
| `mkdocs.yml` | Site config: Material theme, curated `nav`, Mermaid-via-superfences, `strict: true`. |
| `hooks.py` | Build hook that rewrites `*.md` hrefs **inside Mermaid diagrams** to the URLs MkDocs publishes (MkDocs only rewrites `.md` links in prose, not inside fences). |
| `pyproject.toml` / `uv.lock` | Pinned `mkdocs-material` dependency closure. |

`strict: true` means a broken internal link or a `nav` entry pointing nowhere fails
the build — catching link rot in CI instead of shipping a 404.
