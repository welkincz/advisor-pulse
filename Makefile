# Advisor Pulse: the only entry points agents should need (see AGENTS.md §5).
# Targets whose code has not landed yet print the issue that implements them and exit 0.

SHELL := /bin/bash
.DEFAULT_GOAL := help

UV  ?= uv
RUN := $(UV) run
DBT := $(RUN) dbt --no-use-colors
DBT_DIRS := --project-dir dbt --profiles-dir dbt

WEEK  ?= last
WEEKS ?= 8
FROM  ?=
TO    ?=
ARGS  ?=

HAS_WEB := $(wildcard web/package.json)
HAS_DBT := $(wildcard dbt/dbt_project.yml)
HAS_CONTRACTS := $(wildcard src/pulse/contracts/codegen.py)

define todo
	@echo "make $@: not implemented yet (see issue #$(1))."
endef

.PHONY: help
help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-18s %s\n", $$1, $$2}'

# ── Setup and checks ────────────────────────────────────────────────────────

.PHONY: setup
setup: ## Install Python, web and dbt dependencies
	$(UV) sync
ifneq ($(HAS_WEB),)
	pnpm -C web install
endif
ifneq ($(HAS_DBT),)
	$(DBT) deps $(DBT_DIRS)
endif

.PHONY: lint
lint: ## ruff lint + format check
	$(RUN) ruff check .
	$(RUN) ruff format --check .

.PHONY: format
format: ## Apply ruff fixes and formatting
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

.PHONY: typecheck
typecheck: ## mypy (strict) on src/
	$(RUN) mypy

.PHONY: test
test: ## pytest, excluding slow and live tests
	$(RUN) pytest -m "not slow and not live" $(ARGS)

.PHONY: check
check: lint typecheck test contracts-check ## Everything a PR must pass locally

# ── Contracts and fixtures ──────────────────────────────────────────────────

.PHONY: contracts
contracts: ## Write contracts/schemas/*.json and dbt/models/sources.yml from pydantic models
ifneq ($(HAS_CONTRACTS),)
	$(RUN) python -m pulse.contracts.codegen
	$(RUN) python -m pulse.dbt_sources
else
	$(call todo,2)
endif

.PHONY: contracts-check
contracts-check: ## Fail if committed JSON schemas are stale
ifneq ($(HAS_CONTRACTS),)
	$(RUN) python -m pulse.contracts.codegen --check
	$(RUN) python -m pulse.dbt_sources --check
else
	$(call todo,2)
endif

.PHONY: fixtures
fixtures: ## Rebuild tiny deterministic fixtures
	$(RUN) python -m pulse.fixtures

.PHONY: seeds
seeds: ## Export org.yaml to dbt seeds
	$(call todo,23)

# ── Pipeline ────────────────────────────────────────────────────────────────

.PHONY: generate
generate: ## Generate synthetic sources (WEEKS=n)
	$(RUN) pulse generate

.PHONY: run
run: ## One weekly run end to end (WEEK=YYYY-Www)
	$(RUN) pulse run --week $(WEEK)

.PHONY: backfill
backfill: ## Weekly runs over a range (FROM=YYYY-Www TO=YYYY-Www)
	$(RUN) pulse backfill --from $(FROM) --to $(TO)

.PHONY: export
export: ## Export marts to web/public/data
	$(RUN) pulse export

.PHONY: narrative-eval
narrative-eval: ## Live narrative eval pass-rate table (RECORD=1 saves the answers)
	$(RUN) python tests/narrative/eval/run_eval.py --live $(if $(RECORD),--record)

.PHONY: geo
geo: ## Download StatCan boundaries and dissolve district and region polygons
	$(RUN) python geo/build_boundaries.py
	$(RUN) python geo/dissolve.py

# ── dbt ─────────────────────────────────────────────────────────────────────

.PHONY: dbt-build-ci
dbt-build-ci: ## dbt build against fixtures (ARGS='-s model')
	$(RUN) python scripts/ci_warehouse.py
	$(DBT) build $(DBT_DIRS) --target ci $(ARGS)

.PHONY: dbt-docs
dbt-docs: ## dbt docs generate + serve (local warehouse)
	$(DBT) docs generate $(DBT_DIRS)
	$(DBT) docs serve $(DBT_DIRS)

.PHONY: dbt-docs-static
dbt-docs-static: ## Static dbt docs into web/public/lineage
	bash scripts/build_dbt_docs.sh

# ── Web ─────────────────────────────────────────────────────────────────────

.PHONY: web-dev
web-dev: ## Vite dev server on fixtures
	pnpm -C web dev

.PHONY: web-check
web-check: ## Web lint + typecheck + unit tests + build (+ smoke)
	pnpm -C web types:check
	pnpm -C web lint
	pnpm -C web typecheck
	pnpm -C web test
	pnpm -C web build
	pnpm -C web test:smoke

.PHONY: web-types
web-types: ## Generate TS types from contracts/schemas
	pnpm -C web types

.PHONY: clean
clean: ## Remove local data and build output
	rm -rf data web/dist .pytest_cache .mypy_cache .ruff_cache
