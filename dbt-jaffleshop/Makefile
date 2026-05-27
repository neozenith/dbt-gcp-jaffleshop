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

# Export every Make-level variable to recipe environments (covers .env keys + fallbacks above).
export

export DBT_PROFILES_DIR := $(CURDIR)

.PHONY: help install gen seed load clean deps debug build run test compile docs lint fix format pytest

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
	@echo "  lint      sqlfluff lint models"
	@echo "  fix       sqlfluff fix models"
	@echo "  format    sqlfluff format models"
	@echo "  pytest    Run pytest macro tests (parametrized; shells out to dbt)"
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
	uv run dbt docs serve

lint:
	uv run sqlfluff lint models

fix:
	uv run sqlfluff fix models

format:
	uv run sqlfluff format models

pytest:
	uv run pytest

clean:
	rm -rf target dbt_packages logs jaffle-data
