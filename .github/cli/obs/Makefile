# obs — dbt observability CLI.
# Dev command-and-control. Run via `make -C .github/cli/obs <target>` from the repo root
# (no cd needed), or `make <target>` from this directory.

.PHONY: help fix ci sync format lint typecheck test test-e2e generate serve

help:
	@echo "obs dev targets:"
	@echo "  fix        format + lint --fix          (inner loop)"
	@echo "  ci         lint + typecheck + test       (what CI runs; no warehouse)"
	@echo "  format     ruff format"
	@echo "  lint       ruff check"
	@echo "  typecheck  mypy over src/"
	@echo "  test       pytest (pure transform; no BigQuery)"
	@echo "  sync       uv sync"
	@echo "  generate   obs generate (hits prod Elementary via SA impersonation)"
	@echo "  serve      obs serve     (generate + host on :8099)"

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

# Browser-driving e2e over the generated static SPA. NOT part of `ci` (needs a browser
# binary + network for the Plotly/Tailwind CDNs). Installs chromium, then drives it
# against a locally-served fixture bundle (no warehouse).
test-e2e:
	uv run --group e2e playwright install chromium
	uv run --group e2e pytest e2e/ -q

# Live targets — need ADC + tokenCreator on the dbt-dev-elementary SA (see README).
generate:
	uv run obs generate

serve:
	uv run obs serve

# Roll-ups: `fix` is the inner loop; `ci` is the gate. `make fix ci` before pushing.
fix: format
	uvx ruff check src tests --line-length 120 --fix

ci: lint typecheck test
