YEARS ?= 6

# Auto-load KEY=value pairs from .env if present (gitignored — holds GCP project IDs etc.).
-include .env

# Non-empty fallbacks for non-identifying env vars.
# profiles.yml's env_var(..., default) only fires when a var is *unset*; if .env defines a key
# with an empty value (e.g. DBT_BQ_DATASET_DEV=), the env_var default is bypassed and dbt errors
# (typically "Must specify schema"). $(or X,Y) treats empty as falsy, so these guards bridge the gap.
# DBT_BQ_PROJECT_TEST/PROD deliberately have no fallback — wrong-project writes must fail loud.
DBT_TARGET := $(or $(DBT_TARGET),dev)
DBT_ENV_TYPE := $(or $(DBT_ENV_TYPE),$(DBT_TARGET))
DBT_BQ_METHOD := $(or $(DBT_BQ_METHOD),oauth)
DBT_BQ_DATASET_DEV := $(or $(DBT_BQ_DATASET_DEV),dbt_dev)
DBT_BQ_DATASET_TEST := $(or $(DBT_BQ_DATASET_TEST),dbt_test)
DBT_BQ_DATASET_PROD := $(or $(DBT_BQ_DATASET_PROD),analytics)
# Elementary models land in the `elementary` custom schema → upper-cased to ELEMENTARY in
# PROD by generate_schema_name (no slice prefix). This is the dataset `edr` reads from.
DBT_BQ_DATASET_ELEMENTARY := $(or $(DBT_BQ_DATASET_ELEMENTARY),ELEMENTARY)
# Dedicated, narrowly-scoped SA for local Elementary reporting (infra/dbt.tf): prod read +
# create/drop ONLY within the prod ELEMENTARY dataset (edr needs scratch tables; it is not a
# read-only tool). Impersonated via the developer's own ADC, so the global gcloud config is
# never repointed. profiles.yml hardcodes this email in the prod-impersonate outputs; the var
# is here for visibility / `make help`.
ELEMENTARY_SA := $(or $(ELEMENTARY_SA),dbt-dev-elementary@dbt-dev-jaffleshop.iam.gserviceaccount.com)
# Canonical prod GCP project, supplied INLINE by the read-only prod targets below (not a
# global default): profiles.yml keeps DBT_BQ_PROJECT_PROD fail-loud so a stray prod-target
# `build`/`run` write still errors out — only the read-only docs/report recipes hardcode it,
# mirroring what dbt-docs.yml does in CI.
ELEMENTARY_PROD_PROJECT := dbt-prod-jaffleshop
DBT_BQ_LOCATION := $(or $(DBT_BQ_LOCATION),US)
DBT_BQ_THREADS := $(or $(DBT_BQ_THREADS),4)
DBT_BQ_TIMEOUT_SECS := $(or $(DBT_BQ_TIMEOUT_SECS),300)
DBT_BQ_PROJECT_DEV := $(or $(DBT_BQ_PROJECT_DEV),dbt-dev-jaffleshop)
DBT_GIT_BRANCH := $(or $(DBT_GIT_BRANCH),$(shell git rev-parse --abbrev-ref HEAD 2>/dev/null))

# --- dbt state: defer-against-prod + shallow-clone -----------------------------
# Local directory the PROD state manifest is pulled into (gitignored). dbt's --state
# flag points here; both --defer and `dbt clone` read manifest.json from it.
DBT_STATE_DIR := $(or $(DBT_STATE_DIR),prod-state)
# Known-good PROD baseline: dbt-deploy-prod.yml refreshes latest/manifest.json on every
# successful release. `make state-pull` copies it down (your gcloud identity needs
# storage.objectViewer on this bucket — granted to developers in infra/stacks/dbt_platform/dbt.tf).
PROD_ARTEFACTS_BUCKET := $(or $(PROD_ARTEFACTS_BUCKET),gs://dbt-prod-jaffleshop-dbt-artefacts)

# Git ref the adaf check targets diff against for their default --changed-only scope.
# Defaults to main for local dev; override in CI to the PR base, e.g. `make ci BASE_REF=origin/main`.
# NOTE: CI must have BASE_REF reachable locally — use actions/checkout with fetch-depth: 0
# (or `git fetch origin main`) so `git merge-base` can resolve it on a shallow clone.
# The "what changed" detection itself now lives in adaf/gitutil.py (was a shell snippet here).
BASE_REF ?= main

# Export every Make-level variable to recipe environments (covers .env keys + fallbacks above).
export

export DBT_PROFILES_DIR := $(CURDIR)

.PHONY: help install gen seed load clean deps debug build run test compile docs lint lint-fix format format-check deprecations-check docs-coverage doc-columns-coverage tests-coverage checks boundaries system-boundaries-check sdag sdag-serve pytest deploy-dev elementary-report gha-docs state-pull build-defer state-build clone

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
	@echo "  elementary-report  generate the Elementary observability dashboard from PROD"
	@echo "                     (impersonates dbt-dev for read-only prod access; single target)"
	@echo "  gha-docs  simulate .github/workflows/dbt-docs.yml locally: build the static docs +"
	@echo "            sdag viewer + Elementary report into tmp/_site, then serve them"
	@echo "  format    sqlfluff format ALL models (auto-fix layout + keyword case)"
	@echo "  format-check  formatter check on CHANGED models (subset of rules; vs BASE_REF=$(BASE_REF))"
	@echo "  lint      full sqlfluff lint on CHANGED models, all rules (vs BASE_REF=$(BASE_REF))"
	@echo "  lint-fix  sqlfluff fix on CHANGED models (auto-fix all fixable rules)"
	@echo "  --- adaf gates (vs BASE_REF=$(BASE_REF); add --json via 'uv run adaf') ---"
	@echo "  deprecations-check  dbt-autofix dry-run over FOLDERS of CHANGED models"
	@echo "  docs-coverage       model description coverage of CHANGED models (from manifest)"
	@echo "  doc-columns-coverage  resolved column description coverage of CHANGED models (needs catalog.json)"
	@echo "  tests-coverage      test coverage of CHANGED models (from manifest)"
	@echo "  checks              run all adaf check gates over CHANGED models"
	@echo "  boundaries          classify each data-product (selectors.yml) node as a system boundary"
	@echo "  system-boundaries-check  fail if any inbound/outbound data-product boundary node has no tests"
	@echo "  sdag                build the interactive sdag viewer assets into tmp/sdag/"
	@echo "  sdag-serve          generate + host the sdag viewer on http://localhost:8088/sdag.html"
	@echo "  pytest    Run pytest macro + adaf tests (parametrized; shells out to dbt)"
	@echo "  deploy-dev Build dbt against dev + upload artefacts to dev GCS bucket"
	@echo "             (mirrors what CI does for test/prod). Requires gcloud ADC"
	@echo "             set up to impersonate dbt-dev@dbt-dev-jaffleshop.iam.gserviceaccount.com"
	@echo "  --- state: defer-against-prod + shallow-clone (DBT_STATE_DIR=$(DBT_STATE_DIR)) ---"
	@echo "  state-pull  Download PROD latest/manifest.json into $(DBT_STATE_DIR)/ (needs gcloud auth)"
	@echo "  build-defer Build only state:modified+ vs prod, deferring unchanged refs to PROD"
	@echo "              (fast inner loop; reads $(DBT_STATE_DIR)/ — run state-pull first)"
	@echo "  state-build state-pull then build-defer in one step"
	@echo "  clone       Shallow-clone PROD relations into your dev slice (zero-copy BQ CLONE)"
	@echo "              scope with DBT_CLONE_SELECT, e.g. make clone DBT_CLONE_SELECT=marts"
	@echo "  clean     Remove dbt artifacts (target/, dbt_packages/, logs/)"
	@echo ""
	@echo "Environment:"
	@echo "  DBT_PROFILES_DIR=$(DBT_PROFILES_DIR)"
	@echo "  DBT_TARGET=$(DBT_TARGET)"
	@echo "  DBT_ENV_TYPE=$(DBT_ENV_TYPE)"
	@echo "  DBT_GIT_BRANCH=$(DBT_GIT_BRANCH)"

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

# --- Elementary observability report -----------------------------------------
# `edr report` renders the Elementary telemetry tables (dbt run/test results, model
# run-times, anomaly history) into one self-contained HTML dashboard.
#
# This is the single, self-contained target the project goal calls for. It impersonates the
# dedicated dbt-dev-elementary SA (the elementary profile's prod-impersonate output): prod
# read + create/drop ONLY within the prod ELEMENTARY dataset (edr materializes scratch tables,
# so it is not a read-only tool — hence a purpose-built SA rather than widening read-only
# dbt-dev). One-time setup is ordinary user ADC — NOT a repointed global ADC:
#   gcloud auth application-default login    # as a developer listed in infra/dbt-developers.yml
# BigQuery mints the short-lived SA token itself, so your global gcloud config is untouched
# (contrast `make login`, which repoints application-default credentials).
#
# PREREQUISITE: the dbt-dev-elementary SA must be provisioned first (infra/dbt.tf, applied via
# the Terraform pipeline). Until then this target fails with a BigQuery permission error.
#
# DBT_BQ_PROJECT_PROD is supplied inline (profiles.yml keeps it fail-loud); the elementary
# dataset defaults to ELEMENTARY. Output: edr_target/elementary_report.html (gitignored).
# Override ELEMENTARY_REPORT_PATH to write elsewhere (gha-docs points it into the site dir).
ELEMENTARY_REPORT_PATH ?= $(CURDIR)/edr_target/elementary_report.html
elementary-report: deps
	DBT_BQ_PROJECT_PROD=$(ELEMENTARY_PROD_PROJECT) \
	uv run edr report \
	  --profiles-dir "$(CURDIR)" \
	  --profile-target prod-impersonate \
	  --target-path "$(CURDIR)/edr_target" \
	  --file-path "$(ELEMENTARY_REPORT_PATH)"

# --- gha-docs: local fidelity-run of .github/workflows/dbt-docs.yml ------------
# Reproduces the Pages build job's three published artefacts as siblings, then serves
# them — so you can eyeball exactly what a tag/dispatch will publish, without a release.
#   1. dbt docs generate --static   → static_index.html copied to <site>/index.html
#   2. adaf products generate   → <site>/sdag.html (+ graph JSON) lineage viewer
#   3. edr report                   → <site>/elementary_report.html observability dashboard
# Prod reads here impersonate dbt-dev (parity with CI's dbt-prod SA, minus the WIF path).
# Because target.name 'prod-impersonate' is not a valid DBT_ENV_TYPE, DBT_ENV_TYPE=PROD is
# set so data_environment() resolves PROD (unsliced, upper-cased datasets) — see profiles.yml.
GHA_SITE := $(CURDIR)/tmp/_site
gha-docs: deps
	rm -rf "$(GHA_SITE)"
	mkdir -p "$(GHA_SITE)"
	DBT_TARGET=prod-impersonate DBT_ENV_TYPE=PROD DBT_BQ_PROJECT_PROD=$(ELEMENTARY_PROD_PROJECT) \
	  uv run dbt docs generate --target prod-impersonate --static
	cp target/static_index.html "$(GHA_SITE)/index.html"
	DBT_TARGET=prod-impersonate DBT_ENV_TYPE=PROD DBT_BQ_PROJECT_PROD=$(ELEMENTARY_PROD_PROJECT) \
	  uv run adaf products generate -o "$(GHA_SITE)"
	$(MAKE) elementary-report ELEMENTARY_REPORT_PATH="$(GHA_SITE)/elementary_report.html"
	DBT_BQ_PROJECT_PROD=$(ELEMENTARY_PROD_PROJECT) \
	  uv run obs generate -o "$(GHA_SITE)/obs"
	@echo ""
	@echo "Simulated GitHub Pages site assembled in $(GHA_SITE):"
	@echo "  http://localhost:8089/index.html              (dbt docs)"
	@echo "  http://localhost:8089/sdag.html               (data-product lineage)"
	@echo "  http://localhost:8089/elementary_report.html  (Elementary observability)"
	@echo "  http://localhost:8089/obs/obs.html            (obs SPA — overview scatter + run Gantt)"
	@echo "Ctrl-C to stop."
	uv run python -m http.server 8089 --directory "$(GHA_SITE)"

# --- adaf: all CHANGED-model gates (SQLFluff, dbt-autofix, coverage) -------
# The shell that used to live here now lives in the adaf Python package
# (adaf/), which a developer, an agent, or GHA can all invoke identically:
#   uv run adaf check --help
# Each target is a thin delegation. The check commands default to --changed-only
# (vs BASE_REF); pass --all or --select <selector> directly to the CLI for other
# scopes, and --json for machine-readable output.

# SQLFluff: format = opinionated layout+keyword-case subset; lint = full ruleset.
# A check reports (non-zero on drift); --fix applies. Both scoped to CHANGED models.
format-check:
	uv run adaf check format --base-ref $(BASE_REF)

# `format` keeps its historic "fix ALL models" meaning (--fix --all).
format:
	uv run adaf check format --fix --all

lint:
	uv run adaf check lint --base-ref $(BASE_REF)

lint-fix:
	uv run adaf check lint --fix --base-ref $(BASE_REF)

deprecations-check:
	uv run adaf check deprecations --base-ref $(BASE_REF)

docs-coverage:
	uv run adaf check docs --base-ref $(BASE_REF)

doc-columns-coverage:
	uv run adaf check doc-columns --base-ref $(BASE_REF)

tests-coverage:
	uv run adaf check tests --base-ref $(BASE_REF)

# All CHANGED-model gates in one pass; non-zero if any fail.
checks:
	uv run adaf check all --base-ref $(BASE_REF)

# Data-product system-boundary analysis over the named selectors in selectors.yml. Read-only: it
# classifies each node as an inbound/outbound/both/internal boundary. Add --product <name> to scope to
# one product, --show-passes to include internal nodes, --json for the machine payload. Needs the dbt
# project env (.env) since membership comes from `dbt ls`.
boundaries:
	uv run adaf products boundaries

# Gate: fail if any inbound/outbound system-boundary node of a data product has zero tests. Selects by
# data product (selectors.yml), so it is NOT part of `checks` (which is changed-file scoped); run it as
# its own gate. Needs the dbt project env (.env).
system-boundaries-check:
	uv run adaf check system-boundaries

# Build the interactive sdag viewer assets (full + super Cytoscape JSON + HTML/JS) into tmp/sdag/.
sdag:
	uv run adaf products generate

# Generate then host the sdag viewer on http://localhost:8088/sdag.html (Ctrl-C to stop).
sdag-serve:
	uv run adaf products serve

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
	uv run dbt seed --target dev --vars '{"load_source_data": true}'
	uv run dbt build --target dev
	@BUCKET=gs://dbt-dev-jaffleshop-dbt-artefacts; \
	RUN_PREFIX=runs/local-$$(date +%Y%m%d-%H%M%S)-$$(whoami); \
	for f in manifest.json run_results.json catalog.json; do \
	  if [ -f "target/$$f" ]; then \
	    gcloud storage cp "target/$$f" "$$BUCKET/$$RUN_PREFIX/$$f"; \
	  fi; \
	done

# --- dbt state: defer-against-prod + shallow-clone ----------------------------
# Persisted prod state already exists in GCS: dbt-deploy-prod.yml uploads
# manifest/run_results/catalog to runs/<id>/ AND refreshes latest/manifest.json on
# every successful release. These targets are the CONSUMER side — pull that baseline
# down and use it for --defer / --state selection and `dbt clone`.
#
# Auth: all three run against the DEV target. The data-plane access they need is
# ALREADY granted — dbt-dev SA holds dataViewer+jobUser on prod (cross_env_readers in
# infra/stacks/dbt_platform/dbt.tf) and dataEditor on dev. `state-pull` additionally
# needs storage.objectViewer on the prod artefacts bucket (granted to developer_members
# in that same dbt.tf). Run `make login` once to set up gcloud + ADC.

# Download the latest known-good PROD manifest into $(DBT_STATE_DIR)/.
state-pull:
	mkdir -p $(DBT_STATE_DIR)
	gcloud storage cp $(PROD_ARTEFACTS_BUCKET)/latest/manifest.json $(DBT_STATE_DIR)/manifest.json
	@echo "Pulled prod state → $(DBT_STATE_DIR)/manifest.json"

# Build ONLY the models that changed vs the prod baseline (and their children), deferring
# every unselected upstream ref to the live PROD relation instead of rebuilding it. Turns a
# one-line change into a 2-model build, not a 200-model build. --favor-state makes dbt prefer
# the prod relation for deferred refs even when a stale same-named relation exists in your slice.
# Override the selector with DBT_DEFER_SELECT (e.g. state:modified+,tag:nightly).
DBT_DEFER_SELECT ?= state:modified+
build-defer:
	uv run dbt build --select $(DBT_DEFER_SELECT) --defer --favor-state --state $(DBT_STATE_DIR)

# Pull fresh prod state, then defer-build — the one-command inner loop.
state-build: state-pull build-defer

# Shallow-clone PROD relations into your branch-sliced DEV datasets. BigQuery does a zero-copy
# CREATE TABLE … CLONE for tables (no data scanned/billed) and recreates views. Gives you a full,
# queryable copy of real prod data in dev WITHOUT rebuilding from source. Sources come from the
# prod state manifest (dbt-prod-jaffleshop.MARTS.*); targets resolve to dbt-dev-jaffleshop.<branch>__*
# via the naming macros. Scope with DBT_CLONE_SELECT (default: every node in the manifest):
#   make clone DBT_CLONE_SELECT=marts
DBT_CLONE_SELECT ?=
clone:
	uv run dbt clone --state $(DBT_STATE_DIR) $(if $(DBT_CLONE_SELECT),--select $(DBT_CLONE_SELECT),)

clean:
	rm -rf target dbt_packages logs jaffle-data
