YEARS ?= 6

# Auto-load KEY=value pairs from .env if present (gitignored — holds GCP project IDs etc.).
-include .env

# Non-empty fallbacks for non-identifying env vars.
# profiles.yml's env_var(..., default) only fires when a var is *unset*; if .env defines a key
# with an empty value (e.g. DBT_BQ_DATASET_DEV=), the env_var default is bypassed and dbt errors
# (typically "Must specify schema"). $(or X,Y) treats empty as falsy, so these guards bridge the gap.
# DBT_BQ_PROJECT_* deliberately has no fallback — wrong-project writes must fail loud.
DBT_TARGET := $(or $(DBT_TARGET),dev)
DBT_ENV_TYPE := $(or $(DBT_ENV_TYPE),$(DBT_TARGET))
DBT_BQ_METHOD := $(or $(DBT_BQ_METHOD),oauth)
DBT_BQ_DATASET_DEV := $(or $(DBT_BQ_DATASET_DEV),dbt_dev)
DBT_BQ_DATASET_TEST := $(or $(DBT_BQ_DATASET_TEST),dbt_test)
DBT_BQ_DATASET_PROD := $(or $(DBT_BQ_DATASET_PROD),analytics)
DBT_BQ_LOCATION := $(or $(DBT_BQ_LOCATION),US)
DBT_BQ_THREADS := $(or $(DBT_BQ_THREADS),4)
DBT_BQ_TIMEOUT_SECS := $(or $(DBT_BQ_TIMEOUT_SECS),300)
DBT_BQ_PROJECT_DEV := $(or $(DBT_BQ_PROJECT_DEV), dbt-dev-jaffleshop)

# Git ref the cicd_cli check targets diff against for their default --changed-only scope.
# Defaults to main for local dev; override in CI to the PR base, e.g. `make ci BASE_REF=origin/main`.
# NOTE: CI must have BASE_REF reachable locally — use actions/checkout with fetch-depth: 0
# (or `git fetch origin main`) so `git merge-base` can resolve it on a shallow clone.
# The "what changed" detection itself now lives in cicd_cli/gitutil.py (was a shell snippet here).
BASE_REF ?= main

# Export every Make-level variable to recipe environments (covers .env keys + fallbacks above).
export

export DBT_PROFILES_DIR := $(CURDIR)

.PHONY: help install gen seed load clean deps debug build run test compile docs lint lint-fix format format-check deprecations-check docs-coverage columns-coverage tests-coverage checks pytest deploy-dev

help:
	@echo "Targets:"
	@echo "  install   Sync .venv from pyproject.toml + uv.lock (incl. dev group)"
	@echo "  deps      Install dbt packages (dbt deps)"
	@echo "  gen       Generate jafgen data (YEARS=$(YEARS)) into seeds/jaffle-data/"
	@echo "  seed      dbt seed --full-refresh with load_source_data=true"
	@echo "  load      install + gen + seed (one-shot bootstrap)"
	@echo "  debug     dbt debug"
	@echo "  build     dbt build (run + test + seed + snapshot)"
	@echo "  run       dbt run"
	@echo "  test      dbt test"
	@echo "  compile   dbt compile"
	@echo "  docs      dbt docs generate && dbt docs serve"
	@echo "  format    sqlfluff format ALL models (auto-fix layout + keyword case)"
	@echo "  format-check  formatter check on CHANGED models (subset of rules; vs BASE_REF=$(BASE_REF))"
	@echo "  lint      full sqlfluff lint on CHANGED models, all rules (vs BASE_REF=$(BASE_REF))"
	@echo "  lint-fix  sqlfluff fix on CHANGED models (auto-fix all fixable rules)"
	@echo "  --- cicd_cli gates (vs BASE_REF=$(BASE_REF); add --json via 'uv run -m cicd_cli') ---"
	@echo "  deprecations-check  dbt-autofix dry-run over FOLDERS of CHANGED models"
	@echo "  docs-coverage       model description coverage of CHANGED models (from manifest)"
	@echo "  columns-coverage    resolved column description coverage of CHANGED models (needs catalog.json)"
	@echo "  tests-coverage      test coverage of CHANGED models (from manifest)"
	@echo "  checks              run all cicd_cli check gates over CHANGED models"
	@echo "  pytest    Run pytest macro + cicd_cli tests (parametrized; shells out to dbt)"
	@echo "  deploy-dev Build dbt against dev + upload artefacts to dev GCS bucket"
	@echo "             (mirrors what CI does for test/prod). Requires gcloud ADC"
	@echo "             set up to impersonate dbt-dev@dbt-dev-jaffleshop.iam.gserviceaccount.com"
	@echo "  clean     Remove dbt artifacts (target/, dbt_packages/, logs/)"

install:
	uv sync

deps: install
	uv run dbt deps

gen: install
	uv run jafgen $(YEARS)
	rm -rf seeds/jaffle-data
	mv jaffle-data seeds/jaffle-data

seed:
	uv run dbt seed --full-refresh --vars '{"load_source_data": true}'

load: install gen seed

login:
	# Authenticate your use for `gcloud storage cp` commands.
	gcloud auth login --account "$$(git config user.email 2>/dev/null)"

	# Impersonate dbt-dev SA for ADC which dbt profiles.yml needs.
	gcloud auth application-default login --impersonate-service-account=dbt-dev@dbt-dev-jaffleshop.iam.gserviceaccount.com

debug:
	uv run dbt debug

compile:
	uv run dbt compile

docs:
	uv run dbt docs generate

docs-serve: docs
	uv run dbt docs serve

# --- cicd_cli: all CHANGED-model gates (SQLFluff, dbt-autofix, coverage) -------
# The shell that used to live here now lives in the cicd_cli Python package
# (cicd_cli/), which a developer, an agent, or GHA can all invoke identically:
#   uv run -m cicd_cli check --help
# Each target is a thin delegation. The check commands default to --changed-only
# (vs BASE_REF); pass --all or --select <selector> directly to the CLI for other
# scopes, and --json for machine-readable output.

# SQLFluff: format = opinionated layout+keyword-case subset; lint = full ruleset.
# A check reports (non-zero on drift); --fix applies. Both scoped to CHANGED models.
format-check:
	uv run -m cicd_cli check format --base-ref $(BASE_REF)

# `format` keeps its historic "fix ALL models" meaning (--fix --all).
format:
	uv run -m cicd_cli check format --fix --all

lint:
	uv run -m cicd_cli check lint --base-ref $(BASE_REF)

lint-fix:
	uv run -m cicd_cli check lint --fix --base-ref $(BASE_REF)

deprecations-check:
	uv run -m cicd_cli check deprecations --base-ref $(BASE_REF)

docs-coverage:
	uv run -m cicd_cli check docs --base-ref $(BASE_REF)

columns-coverage:
	uv run -m cicd_cli check columns --base-ref $(BASE_REF)

tests-coverage:
	uv run -m cicd_cli check tests --base-ref $(BASE_REF)

# All CHANGED-model gates in one pass; non-zero if any fail.
checks:
	uv run -m cicd_cli check all --base-ref $(BASE_REF)

pytest:
	uv run pytest

# Inner-loop gate, runnable locally or in a PR. `lint` (all rules, changed models)
# is the comprehensive SQL gate and subsumes format-check; compile + pytest validate
# the whole project.
ci: lint compile pytest

# Local-only "deploy" — dbt-dev SA is humans-only per infra/dbt.tf, so dev never
# gets a CI deploy. This target gives developers parity with what CI does for
# test/prod: dbt build + upload manifest/run_results/catalog to the dev artefacts bucket.
# Auth: relies on gcloud ADC being set to impersonate dbt-dev SA (one-time setup):
#   gcloud auth application-default login
#   gcloud config set auth/impersonate_service_account dbt-dev@dbt-dev-jaffleshop.iam.gserviceaccount.com
# Slice from current git branch keeps your work isolated from other devs in dev.
deploy-dev: deps
	DBT_TARGET=dev \
	DBT_BQ_PROJECT_DEV=dbt-dev-jaffleshop \
	DBT_GIT_BRANCH=$$(git rev-parse --abbrev-ref HEAD) \
	uv run dbt seed --target dev --vars '{"load_source_data": true}'
	uv run dbt build --target dev
	@BUCKET=gs://dbt-dev-jaffleshop-dbt-artefacts; \
	RUN_PREFIX=runs/local-$$(date +%Y%m%d-%H%M%S)-$$(whoami); \
	for f in manifest.json run_results.json catalog.json; do \
	  if [ -f "target/$$f" ]; then \
	    gcloud storage cp "target/$$f" "$$BUCKET/$$RUN_PREFIX/$$f"; \
	  fi; \
	done

clean:
	rm -rf target dbt_packages logs jaffle-data
