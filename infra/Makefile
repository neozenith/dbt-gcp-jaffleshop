# infra/Makefile — convenience wrapper around terraform + the bootstrap scripts.
#
# Run from the infra/ directory, or `make -C infra <target>` from the repo root.
#
#   make help          list every target
#   make bootstrap     one-time GCP-side setup for all three projects
#   make plan-dev      terraform plan against dbt-dev-jaffleshop
#   make apply-dev     terraform apply against dbt-dev-jaffleshop
#   make ci            local CI gate (fmt-check + lint)
#
# Per-environment terraform targets are pattern rules — substitute dev/test/prod
# for <env> in init-<env>, plan-<env>, apply-<env>, validate-<env>.

SHELL         := /usr/bin/env bash
.SHELLFLAGS   := -eu -o pipefail -c
.DEFAULT_GOAL := help

ENVS := dev test prod

# Platforms covered by .terraform.lock.hcl. Each entry adds one per-platform
# h1: install-hash to the lock so `terraform init` works on that OS/arch.
# - linux_amd64:  GitHub Actions ubuntu-latest runners.
# - darwin_arm64: Apple Silicon Macs (contributor laptops).
# - darwin_amd64: Intel Macs (legacy contributor laptops).
# Append windows_amd64 / linux_arm64 here if contributors or CI runners need them.
TF_LOCK_PLATFORMS := linux_amd64 darwin_arm64 darwin_amd64

.PHONY: help bootstrap bootstrap-github fmt fmt-check lint docs security lock lock-check validate-all ci

# NOTE: deliberately NOT declaring init-/plan-/apply-/validate-<env> as .PHONY.
# GNU Make 3.81 (macOS default) has a bug where adding pattern-matched targets
# to .PHONY suppresses their pattern rules entirely ("Nothing to be done").
# These targets fire correctly without .PHONY because no real files of those
# names exist to be timestamp-compared.

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | sort \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---- One-time bootstrap ----

bootstrap: ## Run GCP-side bootstrap for every project (idempotent)
	./bootstrap/bootstrap_all.sh

bootstrap-github: ## Create/refresh GitHub Environments + vars (run AFTER bootstrap)
	./bootstrap/bootstrap_github.sh

# ---- Per-environment terraform targets ----
# init-<env>, plan-<env>, apply-<env>, validate-<env>
# `-reconfigure` on init makes env-switching in the same checkout safe.
#
# Implementation note: init is inlined into plan/apply/validate via TF_INIT_CMD
# instead of being a pattern-rule prerequisite (`plan-%: init-%`). The natural
# form trips a known bug in GNU Make 3.81 (the version shipped with macOS) where
# chained pattern rules with the same stem produce "Nothing to be done" silently.
# `brew install make` gives a modern gmake if you'd rather use the natural form.

TF_INIT_CMD = terraform init -backend-config=./backends/$*.config -reconfigure

init-%: ## terraform init -reconfigure for <env>  (e.g. make init-dev)
	$(TF_INIT_CMD)

plan-%: ## terraform plan for <env>
	$(TF_INIT_CMD)
	terraform plan -input=false -var environment=$*

apply-%: ## terraform apply for <env> (-auto-approve)
	$(TF_INIT_CMD)
	terraform apply -input=false -auto-approve -var environment=$*

validate-%: ## terraform validate for <env>
	$(TF_INIT_CMD)
	terraform validate

validate-all: $(addprefix validate-,$(ENVS)) ## validate against every env's backend

# ---- Quality gates ----

fmt: ## terraform fmt -recursive (writes changes)
	terraform fmt -recursive

fmt-check: ## terraform fmt -check -recursive (read-only, CI-safe)
	terraform fmt -check -recursive

lint: ## tflint --recursive (uses .tflint.hcl; first run needs `tflint --init`)
	tflint --recursive

docs: ## Regenerate the terraform-docs section of README.md (between <!-- BEGIN/END_TF_DOCS -->)
	terraform-docs markdown table --output-file README.md --output-mode inject .

security: ## Optional: trivy config scan for IaC misconfigurations (install: brew install trivy)
	trivy config .

lock: ## Regenerate .terraform.lock.hcl with checksums for every platform in TF_LOCK_PLATFORMS
	terraform providers lock $(addprefix -platform=,$(TF_LOCK_PLATFORMS))

lock-check: ## Fail if .terraform.lock.hcl is stale vs. the resolved providers (CI gate; mutates file on drift)
	@terraform providers lock $(addprefix -platform=,$(TF_LOCK_PLATFORMS)) >/dev/null
	@git diff --exit-code .terraform.lock.hcl >/dev/null || \
	  { echo >&2 "ERROR: .terraform.lock.hcl is stale. Run 'make lock' and commit the result."; exit 1; }

ci: fmt-check lint security ## Local CI gate — fmt-check + lint (no cloud calls). Run validate-<env> separately.
