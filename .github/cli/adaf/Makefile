# adaf — Automated Data Assurance Framework CLI.
# Dev command-and-control. Run via `make -C .github/cli/adaf <target>` from the repo root
# (no cd needed), or `make <target>` from this directory.

.PHONY: help fix ci sync format lint typecheck test evals validate \
	adaf-multiversion-ci adaf-multiversion-rebaseline

help:
	@echo "adaf dev targets:"
	@echo "  fix        format + lint --fix          (inner loop)"
	@echo "  ci         lint + typecheck + test       (what CI runs)"
	@echo "  format     ruff format"
	@echo "  lint       ruff check"
	@echo "  typecheck  mypy over src/"
	@echo "  test       pytest (fast unit suite)"
	@echo "  evals      deepeval suite (eval dep-group; installs deepeval)"
	@echo "  validate   adaf rules validate (the catalogue SSoT guard)"
	@echo "  sync       uv sync"

sync:
	uv sync

format:
	uvx ruff format src tests --line-length 120

lint:
	uvx ruff check src tests --line-length 120

typecheck:
	uvx mypy --ignore-missing-imports src

test:
	uv run pytest -q

evals:
	uv run --group eval pytest evals/ -p no:cacheprovider -o addopts=""

validate:
	uv run adaf rules validate

# Roll-ups: `fix` is the inner loop; `ci` is the gate. `make fix ci` before pushing.
fix: format
	uvx ruff check src tests --line-length 120 --fix

ci: lint typecheck test validate

# Docker-backed dbt version-matrix suite (off ci — minutes + image builds + PyPI). Builds + runs one
# image per pinned dbt engine and snapshots adaf's gates vs tests/multiversion/goldens/. Needs Docker.
# `-m multiversion` overrides the pyproject default `-m 'not multiversion'`. See tests/multiversion/README.md.
adaf-multiversion-ci:
	uv run pytest tests/multiversion/test_multiversion.py -m multiversion -s -v

# Deliberate golden re-baseline (review the diff, then commit — never auto-green a run).
adaf-multiversion-rebaseline:
	ADAF_GOLDEN_UPDATE=1 uv run pytest tests/multiversion/test_multiversion.py -m multiversion -s -v
