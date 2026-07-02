# adaf CLI — dev tooling. Run via `make -C .github/cli/adaf <target>` from the repo root
# (the repo's sub-Makefile pattern), or from this directory. `uv run` resolves this
# package's own venv (ruamel + ruff/mypy/pytest) — the dbt/sqlfluff tools it shells out to
# at runtime live in the ROOT venv and aren't needed for lint/type/test.

UV := uv run

.PHONY: help install format lint typecheck test fix ci docs \
	adaf-multiversion-ci adaf-multiversion-rebaseline

help:
	@echo "Targets:"
	@echo "  install    uv sync (this package's venv)"
	@echo "  format     ruff format src/"
	@echo "  lint       ruff check src/"
	@echo "  typecheck  mypy --strict over src/adaf"
	@echo "  test       pytest (multiversion suite deselected by default)"
	@echo "  fix        ruff format + ruff check --fix (the inner-loop autofix)"
	@echo "  ci         lint + typecheck + test (must be green before handoff)"
	@echo "  docs       regenerate the README/AGENTS/CONTRIBUTING TOCs (mdtoc)"
	@echo "  adaf-multiversion-ci          build + run one Docker image per pinned dbt engine and"
	@echo "                                snapshot adaf's gates vs tests/multiversion/goldens/ (needs Docker;"
	@echo "                                off ci — minutes + image builds. See tests/multiversion/README.md)"
	@echo "  adaf-multiversion-rebaseline  same, but rewrite the goldens for engines that ran (deliberate)"

install:
	uv sync

format:
	$(UV) ruff format src

lint:
	$(UV) ruff check src

typecheck:
	$(UV) mypy

test:
	$(UV) --extra fusion pytest   # --extra fusion ⇒ duckdb present so the parquet-reader tests RUN (not skip)

# Inner-loop autofix: format, then apply ruff's safe fixes.
fix:
	$(UV) ruff format src
	$(UV) ruff check --fix src

ci: lint typecheck test

# dbt-core future version matrix integration suite:
# 
# - tests/multiversion/docker/Dockerfile: Single parametrised Dockerfile for testing multiple dbt versions
# - tests/multiversion/fixture: tiny example dbt project as a fixture
# - tests/multiversion/goldens/: Reference working test expectation outputs
#
# The flag `-m multiversion` overrides pytest's pyproject's default `-m 'not multiversion'`. 
adaf-multiversion-ci:
	$(UV) pytest tests/multiversion/test_multiversion.py -m multiversion -s -v

# Deliberate golden re-baseline (review the diff, then commit with the pin bump — never auto-green a run).
adaf-multiversion-rebaseline:
	ADAF_GOLDEN_UPDATE=1 $(UV) pytest tests/multiversion/test_multiversion.py -m multiversion -s -v

# Keep the doc TOCs current. mdtoc edits in place between the <!--TOC--> markers.
docs:
	uvx --from md-toc md_toc --in-place --no-list-coherence github --header-levels 4 \
		README.md AGENTS.md CONTRIBUTING.md
