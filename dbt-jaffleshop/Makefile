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

# Git ref that the CHANGED-model targets (lint / lint-fix / format-check) diff against.
# Defaults to main for local dev; override in CI to the PR base, e.g. `make ci BASE_REF=origin/main`.
# NOTE: CI must have BASE_REF reachable locally — use actions/checkout with fetch-depth: 0
# (or `git fetch origin main`) so `git merge-base` can resolve it on a shallow clone.
BASE_REF ?= main

# Shell snippet (expanded inside recipes) that prints the changed model paths:
# models/**/*.sql differing from BASE_REF in ANY git state — committed, staged,
# unstaged, OR untracked-new. `git diff <merge-base>` covers tracked changes;
# `ls-files --others` adds untracked files. --relative strips the dbt-jaffleshop/
# prefix so paths are valid for sqlfluff run from here. Single source of truth for
# "what changed", shared by lint, lint-fix, and format-check.
CHANGED_MODELS = { \
	  git diff --name-only --relative --diff-filter=d $$(git merge-base $(BASE_REF) HEAD) -- 'models/*.sql'; \
	  git ls-files --others --exclude-standard -- 'models/*.sql'; \
	} | sort -u

# Export every Make-level variable to recipe environments (covers .env keys + fallbacks above).
export

export DBT_PROFILES_DIR := $(CURDIR)

.PHONY: help install gen seed load clean deps debug build run test compile docs lint lint-fix format format-check pytest deploy-dev

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
	@echo "  pytest    Run pytest macro tests (parametrized; shells out to dbt)"
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

debug:
	uv run dbt debug

compile:
	uv run dbt compile

docs:
	uv run dbt docs generate

docs-serve: docs
	uv run dbt docs serve

# --- SQLFluff: two pairs, both scoped to CHANGED models (vs BASE_REF) ---------
# format / format-check : opinionated FORMATTER  — layout + keyword case only,
#                         the subset `sqlfluff format` can auto-fix.
# lint   / lint-fix     : full LINTER             — every rule in .sqlfluff.
# A *-check/lint target reports; its sibling auto-fixes. lint ⊇ format-check, so
# a green `lint` implies a green `format-check`.

# Auto-fix formatting (layout + keyword case) across ALL models. Idempotent + safe.
format:
	uv run sqlfluff format models

# Report formatting drift on CHANGED models only, scoped to the rules `format`
# fixes, so any failure here is always resolvable by `make format`.
format-check:
	@CHANGED="$$( $(CHANGED_MODELS) )"; \
	if [ -z "$$CHANGED" ]; then \
	  echo "format-check: no changed models vs $(BASE_REF) — nothing to check."; \
	else \
	  echo "format-check: checking changed models vs $(BASE_REF):"; \
	  echo "$$CHANGED" | sed 's/^/  /'; \
	  uv run sqlfluff lint --rules layout,capitalisation.keywords $$CHANGED; \
	fi

# Full lint (ALL rules) on CHANGED models only — the comprehensive PR gate.
lint:
	@CHANGED="$$( $(CHANGED_MODELS) )"; \
	if [ -z "$$CHANGED" ]; then \
	  echo "lint: no changed models vs $(BASE_REF) — nothing to check."; \
	else \
	  echo "lint: linting changed models vs $(BASE_REF):"; \
	  echo "$$CHANGED" | sed 's/^/  /'; \
	  uv run sqlfluff lint $$CHANGED; \
	fi

# Auto-fix every fixable violation on CHANGED models (ALL rules). Whatever remains
# afterward is a rule sqlfluff can't auto-fix and must be corrected by hand.
lint-fix:
	@CHANGED="$$( $(CHANGED_MODELS) )"; \
	if [ -z "$$CHANGED" ]; then \
	  echo "lint-fix: no changed models vs $(BASE_REF) — nothing to fix."; \
	else \
	  echo "lint-fix: fixing changed models vs $(BASE_REF):"; \
	  echo "$$CHANGED" | sed 's/^/  /'; \
	  uv run sqlfluff fix $$CHANGED; \
	fi

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
