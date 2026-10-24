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
	cd web && pnpm install
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
check: lint typecheck test contracts-check seeds-check ## Everything a PR must pass locally

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

.PHONY: seeds seeds-check
seeds: ## Export org.yaml and shipped FSA codes to dbt seeds
	$(RUN) python -m pulse.seeds

seeds-check: ## Fail if committed dbt seeds are stale
	$(RUN) python -m pulse.seeds --check

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

# Each dir is a built data dir (generate --backfill, then one run); ADR 0006 has the commands.
BACKTEST_DIRS ?= data
.PHONY: backtest
backtest: ## Score the report's flags against the generator's ground truth (BACKTEST_DIRS='tune held-out', ARGS='--tune')
	$(RUN) python -m pulse.quality.backtest_cli $(BACKTEST_DIRS) $(ARGS)

.PHONY: export
export: ## Export marts to web/public/data
	$(RUN) pulse export

# The poster (frame 320) is the four national measures, fully counted up (video/src/Recap.tsx SCENES).
.PHONY: video
video: ## Weekly recap video from the published export into web/public/recap (WEEK=… optional; needs video/ installed)
	$(RUN) pulse recap --exports web/public/data --out web/public/recap/recap.json $(if $(WEEK),--week $(WEEK))
	cd video && pnpm exec remotion render src/index.ts Recap ../web/public/recap/recap.mp4 --props=../web/public/recap/recap.json --log=error
	cd video && pnpm exec remotion still src/index.ts Recap ../web/public/recap/poster.jpg --frame=320 --props=../web/public/recap/recap.json --log=error

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
	$(DBT) seed $(DBT_DIRS) --target ci
	$(DBT) build $(DBT_DIRS) --target ci --indirect-selection=buildable $(ARGS)

.PHONY: crosscheck-kpi
crosscheck-kpi: ## Recompute the lead KPI from the raw extracts and compare it with the marts (PULSE_DATA_DIR)
	$(RUN) python scripts/crosscheck_kpi.py --data-dir "$${PULSE_DATA_DIR:-data}"

.PHONY: dbt-docs
dbt-docs: ## dbt docs generate + serve (local warehouse)
	$(DBT) docs generate $(DBT_DIRS)
	$(DBT) docs serve $(DBT_DIRS)

.PHONY: dbt-docs-static
dbt-docs-static: ## Static dbt docs into web/public/lineage
	bash scripts/build_dbt_docs.sh

# ── Web ─────────────────────────────────────────────────────────────────────

.PHONY: web-dev
web-dev: ## Vite dev server on fixtures (an Ontario and Quebec slice)
	cd web && pnpm dev

.PHONY: web-dev-latest
web-dev-latest: ## Vite dev server on the latest published weekly export: every region, every week (needs gh)
	scripts/fetch_latest_export.sh data/web-latest
	cd web && PULSE_FIXTURES_DIR=$(CURDIR)/data/web-latest pnpm dev

.PHONY: web-audit-latest
web-audit-latest: ## Cross-view number audit on the latest weekly export (EXPORTS=dir skips the download; WEEK=2026-W41 audits an earlier week; needs gh)
	$(if $(EXPORTS),,scripts/fetch_latest_export.sh data/web-latest)
	cd web && PULSE_AUDIT_EXPORTS=$(abspath $(or $(EXPORTS),data/web-latest)) $(if $(filter-out last,$(WEEK)),PULSE_AUDIT_WEEK=$(WEEK)) pnpm exec playwright test tests/audit.spec.ts --reporter=line

.PHONY: web-check
web-check: ## Web lint + typecheck + unit tests + build (+ smoke)
	cd web && pnpm types:check
	cd web && pnpm lint
	cd web && pnpm typecheck
	cd web && pnpm test
	cd web && pnpm build
	cd web && pnpm test:smoke

.PHONY: web-types
web-types: ## Generate TS types from contracts/schemas
	cd web && pnpm types

.PHONY: clean
clean: ## Remove local data and build output
	rm -rf data web/dist .pytest_cache .mypy_cache .ruff_cache
