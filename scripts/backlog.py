"""Source of truth for the Advisor Pulse issue backlog.

Renders:
  docs/BACKLOG.md                    human-readable backlog
  scripts/create_github_backlog.sh   gh commands: labels, milestones, issues

Issue numbers are assigned in list order, starting at 1, so the shell script must
run on a repo with no issues or PRs yet. The script verifies each number as it goes.

Usage: python3 scripts/backlog.py
"""

from __future__ import annotations

from pathlib import Path

REPO = "welkincz/advisor-pulse"
ROOT = Path(__file__).resolve().parent.parent

MILESTONES = [
    ("M1", "M1 · Synthetic multi-source data", "Seeded generator for the 'Snowflake' and 'Teradata' sources, realistic dirt, defect manifest, contracts and fixtures."),
    ("M2", "M2 · Org hierarchy & geography", "National > Region > District > Branch > Advisor, SCD2 advisor, FSA geography and StatCan boundaries."),
    ("M3", "M3 · Incremental ingestion", "Watermarks, file manifest, idempotent loads, quarantine."),
    ("M4", "M4 · dbt modeling", "Staging / intermediate / marts star schema, tests, contracts, lineage docs."),
    ("M5", "M5 · Orchestration, checks & AI narrative", "Weekly GitHub Actions run, retries, checks, alerting, backfill, state, export, deploy, grounded LLM narratives."),
    ("M6", "M6 · Pipeline visualization", "React Flow replay of the last weekly run: status, rows, durations."),
    ("M7", "M7 · Web dashboard", "pulse.charliebuild.com: DuckDB-WASM, drill-down, map, KPI trends, motion."),
    ("M8", "M8 · Tableau & case study", "Google Sheets feed, Tableau Public companion, case study, charliebuild entry."),
]

LABELS = [
    ("area:infra", "5319e7", "Repo, tooling, CI, hosting"),
    ("area:contracts", "1d76db", "Schemas, contracts, fixtures"),
    ("area:data-gen", "0e8a16", "Synthetic source generator"),
    ("area:ingest", "006b75", "Watermarks, loaders, quarantine"),
    ("area:dbt", "fbca04", "dbt models and tests"),
    ("area:geo", "c2e0c6", "Boundaries and geography"),
    ("area:orchestration", "b60205", "Runner, checks, workflows, state"),
    ("area:ai", "d93f0b", "LLM narrative"),
    ("area:pipeline-viz", "bfd4f2", "React Flow pipeline view"),
    ("area:frontend", "0052cc", "Web dashboard"),
    ("area:tableau", "e99695", "Tableau Public companion"),
    ("area:docs", "c5def5", "Docs and case study"),
    ("status:ready", "0e8a16", "All dependencies closed; can be claimed"),
    ("status:blocked", "d73a4a", "Waiting on dependencies"),
    ("status:in-progress", "fbca04", "Claimed by an agent"),
    ("size:S", "ededed", "A few hours"),
    ("size:M", "cccccc", "About a day for one agent"),
    ("agent:claude", "8250df", "Reasoning-heavy or cross-cutting"),
    ("agent:cursor", "1f6feb", "Implementation"),
    ("agent:codex", "2da44e", "Well-bounded backend"),
    ("agent:human", "6e7781", "Needs Charlie: accounts, secrets, publishing"),
    ("agent:any", "afb8c1", "Any agent"),
    ("wave:0", "f9d0c4", "Foundation"),
    ("wave:1", "fef2c0", "Parallel build-out"),
    ("wave:2", "d4c5f9", "Integration"),
    ("wave:3", "c2e0c6", "Polish"),
    ("alert:pipeline", "b60205", "Opened automatically by a failed weekly run"),
]

# Each issue: key, title, milestone, area, agent, size, wave, owns, context, ac, verify, deps
ISSUES: list[dict] = [
    # ───────────────────────── Wave 0: foundation ─────────────────────────
    dict(
        key="scaffold", title="Scaffold repo: uv, ruff, pytest, Makefile, layout", milestone="M1",
        area="infra", agent="claude", size="M", wave=0,
        owns=["pyproject.toml", "Makefile", "src/pulse/__init__.py", "src/pulse/cli.py", ".gitignore", ".env.example", ".github/pull_request_template.md", ".github/ISSUE_TEMPLATE/", "README.md", "LICENSE"],
        context="Create the skeleton from PLAN.md §4 so every later issue has a home. Python 3.12 with uv, ruff (lint and format), mypy, pytest with markers (unit, integration, slow, live). A `pulse` Typer CLI with stub subcommands. Makefile targets from AGENTS.md §5 (stubs that exit 0 with a message are fine where the code does not exist yet).",
        ac=[
            "`uv sync && make check` passes on a clean clone",
            "`pulse --help` lists generate, ingest, run, backfill, export, narrate",
            "Directory layout matches PLAN.md §4 (empty dirs keep a README or .gitkeep)",
            "PR template has sections: Summary, Closes, Acceptance evidence, Contract changes, Dependencies added",
            "Issue template `agent-task.md` mirrors the backlog issue body format",
            "README states that all data is synthetic and the bank is fictional",
        ],
        verify="make setup && make check && uv run pulse --help",
        deps=[],
    ),
    dict(
        key="contracts", title="Data contracts as code (pydantic → JSON Schema)", milestone="M1",
        area="contracts", agent="claude", size="M", wave=0,
        owns=["src/pulse/contracts/", "contracts/schemas/", "tests/contracts/"],
        context="Encode every table in PLAN.md §6 as pydantic models: sources (6.1–6.2), raw metadata columns (6.4), meta/quarantine (6.5), exports (6.9), run_log, pipeline_graph, narrative. Generate JSON Schema files, which the frontend later uses to generate TypeScript types. Contracts carry a `schema_version`.",
        ac=[
            "One pydantic model per table in PLAN.md §6.1, 6.2, 6.4, 6.5 and 6.9, with column names and types matching the dictionary exactly",
            "Enum values (activity type, status, channel, outcome, product line, segment, role, reason) defined once and reused",
            "`make contracts` writes `contracts/schemas/*.json`; `make contracts-check` fails if the committed schemas are stale",
            "Unit tests: a valid sample row passes; each enum, nullability and range rule rejects a bad row",
            "A helper exposes the Arrow schema for each Parquet contract (used by the generator and export)",
        ],
        verify="make contracts-check && uv run pytest tests/contracts",
        deps=["scaffold"],
    ),
    dict(
        key="orgref", title="Org hierarchy reference data (org.yaml)", milestone="M2",
        area="contracts", agent="claude", size="S", wave=0,
        owns=["reference/org.yaml", "reference/activity_types.csv", "src/pulse/reference.py", "tests/test_reference.py"],
        context="Author the fictional org: 4 regions, 14 districts (PLAN.md §5), ~120 branches, each in a real FSA in the right province and plausible area (e.g. GTA branches in M-prefixed FSAs). Branch names are fictional (neighbourhood + 'Branch'). Include a loader with validation.",
        ac=[
            "org.yaml has 4 regions, 14 districts, 110–130 branches, with branch counts weighted roughly by population",
            "Every branch FSA matches the Canadian FSA regex and its first letter matches the district's province",
            "Loader returns typed objects; tests check unique IDs, every district has ≥ 3 branches, and no orphans",
            "activity_types.csv matches PLAN.md §5",
        ],
        verify="uv run pytest tests/test_reference.py",
        deps=["contracts"],
    ),
    dict(
        key="fixtures", title="Tiny deterministic fixtures for every contract", milestone="M1",
        area="contracts", agent="claude", size="M", wave=0,
        owns=["fixtures/", "src/pulse/fixtures.py", "tests/test_fixtures.py"],
        context="Hand-designed (not randomly generated) small datasets so ingestion, dbt, export, frontend and pipeline viz can all be built in parallel before the generator exists. They cover 2 regions, 3 districts, 6 branches, 20 advisors (with 2 transfers), 200 clients, and 4 weeks of activity, including one example of every defect in PLAN.md §5. Fixture exports and run_log.json must look like real output, so the frontend can develop against them.",
        ac=[
            "`make fixtures` deterministically rebuilds fixtures/sources (Parquet, SQLite, CSV) and fixtures/exports (Parquet + JSON); a second run produces byte-identical files",
            "Every file validates against its contract",
            "fixtures/defects.json lists every injected defect with row identifiers",
            "fixtures/run_log.json covers SUCCESS, WARN and one FAILED-then-retried stage; fixtures/pipeline_graph.json has every stage node",
            "fixtures/narratives/ has one narrative file in the narrative contract shape",
            "Total fixtures size < 2 MB",
        ],
        verify="make fixtures && git diff --exit-code fixtures/ && uv run pytest tests/test_fixtures.py",
        deps=["contracts", "orgref"],
    ),
    dict(
        key="ci", title="PR CI workflow (lint, tests, contracts, dbt, web)", milestone="M5",
        area="infra", agent="cursor", size="S", wave=0,
        owns=[".github/workflows/ci.yml"],
        context="GitHub Actions on pull_request and push to main. Jobs use path filters: python (ruff, mypy, pytest -m 'not slow and not live', contracts-check), dbt (`make dbt-build-ci`, skipped until dbt/ has models), web (`make web-check`, skipped until web/package.json exists). Cache uv and pnpm.",
        ac=[
            "CI runs on a PR and reports separate python, dbt and web checks",
            "Jobs skip cleanly (green) when their directory has no relevant changes or does not exist yet",
            "A deliberately failing test makes the python job fail (demonstrated in PR, then reverted)",
            "Total wall time < 6 min on the scaffold",
        ],
        verify="Open the PR and check the Actions tab",
        deps=["scaffold"],
    ),
    dict(
        key="depsbot", title="Dependency bot: flip status:blocked → status:ready", milestone="M5",
        area="infra", agent="cursor", size="S", wave=0,
        owns=[".github/workflows/deps.yml", "scripts/deps_bot.py"],
        context="When an issue closes (or a body is edited), find open issues whose body contains `Depends on: #a, #b`. If all listed issues are closed, swap `status:blocked` for `status:ready` and comment once. Uses GITHUB_TOKEN only.",
        ac=[
            "Parser handles `Depends on: none`, `#3`, `#3, #12` and extra whitespace (unit tested)",
            "Closing the last dependency of an issue relabels it within one workflow run",
            "Idempotent: rerunning makes no duplicate comments",
            "Never touches issues labelled status:in-progress",
        ],
        verify="uv run pytest tests/test_deps_bot.py; then close a test issue in the repo",
        deps=["scaffold"],
    ),
    dict(
        key="meta", title="Warehouse layer: DuckDB connection, meta + quarantine schemas", milestone="M3",
        area="ingest", agent="claude", size="M", wave=0,
        owns=["src/pulse/warehouse.py", "src/pulse/ingest/meta.py", "tests/ingest/test_meta.py"],
        context="A single module owns the DuckDB connection (path from PULSE_DATA_DIR), creates the schemas raw, meta and quarantine, and creates the tables from PLAN.md §6.5. It provides a small repository API: get/set watermark, record manifest entry, is_file_loaded(path, sha), write run_log row, write check_result, write rejected rows. Watermark and manifest writes take an optional open transaction.",
        ac=[
            "`init_warehouse()` is idempotent (safe to call repeatedly)",
            "Table DDL matches the contracts (test compares DuckDB DESCRIBE to the pydantic models)",
            "A transaction that raises leaves watermark and manifest unchanged (tested)",
            "is_file_loaded distinguishes same path with a different sha256",
        ],
        verify="uv run pytest tests/ingest/test_meta.py",
        deps=["contracts"],
    ),
    dict(
        key="dbtscaffold", title="dbt project scaffold (dbt-duckdb, sources, conventions)", milestone="M4",
        area="dbt", agent="claude", size="M", wave=0,
        owns=["dbt/dbt_project.yml", "dbt/profiles.yml", "dbt/packages.yml", "dbt/models/sources.yml", "dbt/macros/", "dbt/seeds/", "dbt/models/marts/dim_date.sql", "dbt/models/marts/dim_date.yml"],
        context="dbt-duckdb with targets `dev` (data/warehouse.duckdb) and `ci` (a warehouse built from fixtures by `make dbt-build-ci`, which first ingests fixtures). Declare all raw sources with freshness config. Folder-level materializations: staging = view, intermediate = table or ephemeral, marts = table, contracts enforced. Add a macro for ISO week IDs and a macro `toronto_date(ts)`. Build dim_date as a worked example of the per-model yml convention.",
        ac=[
            "`make dbt-build-ci` runs green on fixtures, building dim_date",
            "sources.yml declares every raw table with descriptions and a loaded_at_field",
            "dim_date has a contract and tests (unique, not_null, accepted ISO week format)",
            "README in dbt/ explains the layer conventions and the one-yml-per-model rule",
        ],
        verify="make dbt-build-ci",
        deps=["contracts", "fixtures", "meta"],
    ),
    dict(
        key="webscaffold", title="Web scaffold: Vite + React + TS, tokens, routes, deploy config", milestone="M7",
        area="frontend", agent="claude", size="M", wave=0,
        owns=["web/"],
        context="Vite + React 18 + TypeScript + pnpm. Port charliebuild's tokens (paper, ink, muted, rule, signal, focus; light and dark) into `web/src/theme/tokens.css`. Add route shells for /, /r/:region(/d/:district(/b/:branch(/a/:advisor))), /map, /pipeline, /quality, /case-study. `web/public/data` points at fixtures/exports in dev. Add Cloudflare `_redirects` (SPA fallback) and `_headers` (no-cache for manifest.json and run_log.json). Generate TS types from contracts/schemas.",
        ac=[
            "`make web-dev` serves every route shell; `make web-check` (eslint, tsc, vite build) passes",
            "Tokens only: a lint rule or test blocks raw hex colours outside tokens.css",
            "Dark mode follows prefers-color-scheme; reduced motion is wired to a global hook",
            "TS types are generated from contracts/schemas and committed by `make web-types`",
            "Footer copy says 'Weekly batch report · synthetic data · fictional bank'",
        ],
        verify="make web-check",
        deps=["scaffold", "contracts"],
    ),
    dict(
        key="runner", title="Runner skeleton: stage DAG, run_id, retries, run_log", milestone="M5",
        area="orchestration", agent="claude", size="M", wave=0,
        owns=["src/pulse/runner/", "tests/runner/"],
        context="`pulse run --week YYYY-Www` executes registered stages in DAG order: restore_state, generate, ingest, dbt_build, checks, narrate, export, publish_sheets, persist_state. Stages are plain functions that return a StageResult(rows_in, rows_out, rows_quarantined, status, message). The runner adds tenacity retries (3 attempts, exponential backoff with jitter, only for retryable exceptions), writes one run_log row per attempt, stops downstream stages on FAIL, and exports the DAG as pipeline_graph nodes and edges. Stages that do not exist yet are no-ops returning SKIPPED.",
        ac=[
            "A run with all stub stages writes a complete run_log with SUCCESS/SKIPPED rows",
            "A stage raising a retryable error twice then succeeding shows attempts 1–3 in run_log (tested with a fake clock, no real sleep)",
            "A FAILED stage marks downstream stages SKIPPED and the process exits non-zero",
            "`pulse run --dry-run` prints the plan without executing",
            "run_log.json export validates against its contract",
        ],
        verify="uv run pytest tests/runner",
        deps=["meta"],
    ),
    dict(
        key="accounts", title="Accounts and secrets: Cloudflare Pages, R2, Anthropic, Google SA", milestone="M5",
        area="infra", agent="human", size="S", wave=0,
        owns=["(GitHub repo settings)"],
        context="Charlie sets up the external accounts. Agents cannot do this step.",
        ac=[
            "Cloudflare Pages project `advisor-pulse` exists; custom domain pulse.charliebuild.com is attached",
            "R2 bucket `advisor-pulse-state` exists, with an API token scoped to it",
            "Google Cloud service account created and a Google Sheet shared with it as editor",
            "Repo secrets set: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, ANTHROPIC_API_KEY, GOOGLE_SERVICE_ACCOUNT_JSON, GSHEET_ID",
            "Branch protection on main: CI required, squash only",
        ],
        verify="gh secret list --repo welkincz/advisor-pulse",
        deps=[],
    ),
    # ───────────────────────── Wave 1: data generation ─────────────────────────
    dict(
        key="genadvisor", title="Generator: advisor master, assignments and transfers ('Teradata')", milestone="M1",
        area="data-gen", agent="codex", size="M", wave=1,
        owns=["src/pulse/generate/advisors.py", "tests/generate/test_advisors.py"],
        context="From org.yaml, create ~900 advisors (Faker en_CA names) across branches by role mix, with hire dates over 10 years. Simulate assignment events week by week: transfers (~1.5% of advisors per month, mostly within district, sometimes cross-region), promotions, and terminations with backfill hires. Write the ADVSR, ADVSR_ASGN and BRNCH tables into data/sources/teradata/edw.sqlite using the Teradata-style column names in PLAN.md §6.2.",
        ac=[
            "Same seed gives identical output; a different seed gives different output",
            "Every advisor has exactly one HIRE event; events are ordered and never overlap",
            "Transfer rate over 104 weeks is within 1.2–1.8% of advisors per month",
            "Output validates against the source contracts",
            "Runs in < 10 s for the default scale",
        ],
        verify="uv run pytest tests/generate/test_advisors.py",
        deps=["contracts", "orgref"],
    ),
    dict(
        key="genclient", title="Generator: client dimension with postal codes ('Teradata')", milestone="M1",
        area="data-gen", agent="codex", size="M", wave=1,
        owns=["src/pulse/generate/clients.py", "tests/generate/test_clients.py"],
        context="~150k clients assigned to a primary advisor and branch. Postal code = an FSA near the branch (same or neighbouring FSA from a per-district FSA pool) plus a random LDU. Segments by mix; birth year; tenure. Write the CLNT table to SQLite, and daily CSV deltas `client_YYYYMMDD.csv` with new clients, closures and re-assignments (2% per quarter). Clean values only here; dirt is added by the dirt module.",
        ac=[
            "Postal codes match the Canadian regex before dirt is applied, and the FSA's province matches PROV_CD",
            "Re-assignment rate is within 1.5–2.5% per quarter; deltas only contain changed rows, with LAST_UPD_TS set",
            "Deterministic by seed; validates against the contract",
            "Default scale runs in < 30 s",
        ],
        verify="uv run pytest tests/generate/test_clients.py",
        deps=["contracts", "orgref"],
    ),
    dict(
        key="genactivity", title="Generator: weekly activity facts ('Snowflake' Parquet)", milestone="M1",
        area="data-gen", agent="codex", size="M", wave=1,
        owns=["src/pulse/generate/activity.py", "tests/generate/test_activity.py"],
        context="For each ISO week, generate activities per active advisor (as-of the assignment history) with realistic patterns: weekday peaks, a holiday dip (Canadian stat holidays), seasonal RRSP-season lift in Feb, advisor-level productivity variation, and some district-level 'stories' (one district trending down over 8 weeks, one improving) so the narrative has something to say. Appointments are booked from calls (BOOKED_FROM_ACTIVITY_ID), then complete, no-show or cancel later. Write `extract_date=YYYY-MM-DD/part-NNN.parquet`.",
        ac=[
            "Activity is only generated for advisors active at that date, at the branch they were assigned to at that date",
            "Appointment status transitions are consistent (no COMPLETED before SCHEDULED_TS; no_show only for appointments)",
            "Weekly volume is ~15k ± 20% at default scale; the configured district stories are visible in a test aggregate",
            "Deterministic per (seed, week); Parquet schema equals the contract's Arrow schema",
        ],
        verify="uv run pytest tests/generate/test_activity.py",
        deps=["genadvisor", "genclient"],
    ),
    dict(
        key="gendirt", title="Generator: dirt injection + defect manifest", milestone="M1",
        area="data-gen", agent="codex", size="M", wave=1,
        owns=["src/pulse/generate/dirt.py", "tests/generate/test_dirt.py"],
        context="A post-processing module that applies the defects in PLAN.md §5 at configured rates and records each one in `defects/YYYY-Www.json` (defect type, table, natural key or row number, expected handling rule). This is the ground truth the DQ tests reconcile against.",
        ac=[
            "Every defect type in PLAN.md §5 is implemented, and its rate is configurable (0 disables it)",
            "The defect manifest lists exactly the rows modified (test: applying with rate 0 gives an identical file and an empty manifest)",
            "Postal code variants cover lowercase, missing space, hyphen, trailing space, US ZIP and null",
            "Deterministic per (seed, week)",
        ],
        verify="uv run pytest tests/generate/test_dirt.py",
        deps=["genactivity"],
    ),
    dict(
        key="genincr", title="Generator: incremental weekly mode + late arrivals", milestone="M1",
        area="data-gen", agent="codex", size="S", wave=1,
        owns=["src/pulse/generate/cli.py", "src/pulse/generate/late.py", "tests/generate/test_incremental.py"],
        context="`pulse generate --week 2026-W40` emits only that week's extracts, plus late records for up to 3 prior weeks and re-sent rows with status updates. `--backfill --from --to` loops weeks. Generating weeks one by one must produce the same set of files as a backfill over the same range.",
        ac=[
            "Weekly mode writes only new extract_date partitions and new CSV deltas; it never rewrites existing files",
            "Generating W1..W8 one at a time is byte-identical to a backfill of W1..W8",
            "Late-arrival share is within 3–5% of rows",
        ],
        verify="uv run pytest tests/generate/test_incremental.py -m 'not slow'",
        deps=["genactivity", "gendirt"],
    ),
    # ───────────────────────── Wave 1: ingestion ─────────────────────────
    dict(
        key="ingactivity", title="Ingest 'Snowflake' activity Parquet incrementally", milestone="M3",
        area="ingest", agent="codex", size="M", wave=1,
        owns=["src/pulse/ingest/snowflake.py", "tests/ingest/test_snowflake.py"],
        context="Discover partitions under sources/snowflake/activity, skip files already in load_manifest (same path and sha256), and read only rows with _EXTRACTED_AT > watermark. Pass rows through validation (hook from the quarantine issue; until then a pass-through), then write raw.snowflake__activity with the metadata columns using delete+insert by _batch_id. Update watermark and manifest in the same transaction.",
        ac=[
            "Loading fixtures twice leaves raw row counts unchanged; the second run reports SKIPPED_DUPLICATE",
            "A modified file (same path, new hash) loads as a new batch",
            "An exception mid-batch leaves raw, watermark and manifest unchanged",
            "Returns a StageResult with rows_in, rows_out and rows_quarantined",
        ],
        verify="uv run pytest tests/ingest/test_snowflake.py",
        deps=["meta", "fixtures"],
    ),
    dict(
        key="ingclient", title="Ingest 'Teradata' client SQLite snapshot + CSV deltas", milestone="M3",
        area="ingest", agent="codex", size="M", wave=1,
        owns=["src/pulse/ingest/teradata_client.py", "tests/ingest/test_teradata_client.py"],
        context="The first load takes the CLNT table snapshot from SQLite. Later loads take daily CSV deltas newer than the LAST_UPD_TS watermark, in file-date order. Load into raw.teradata__clnt with the same manifest and transaction semantics as the activity loader. CSV parsing must tolerate quoted fields and BOM.",
        ac=[
            "Snapshot then deltas gives the same final state as applying the generator's change log (tested on fixtures)",
            "Re-run is a no-op; a delta older than the watermark is skipped and logged",
            "Malformed CSV lines go to quarantine with rule DQ005, not crash the load",
        ],
        verify="uv run pytest tests/ingest/test_teradata_client.py",
        deps=["meta", "fixtures"],
    ),
    dict(
        key="inghr", title="Ingest 'Teradata' advisor, assignment and branch tables", milestone="M3",
        area="ingest", agent="codex", size="S", wave=1,
        owns=["src/pulse/ingest/teradata_hr.py", "tests/ingest/test_teradata_hr.py"],
        context="Load ADVSR, ADVSR_ASGN and BRNCH incrementally by LAST_UPD_TS into raw.teradata__* tables, with manifest and watermark semantics.",
        ac=[
            "Incremental on LAST_UPD_TS; re-run is a no-op",
            "All three tables are loaded in one transaction per run",
            "Validates against contracts",
        ],
        verify="uv run pytest tests/ingest/test_teradata_hr.py",
        deps=["meta", "fixtures"],
    ),
    dict(
        key="ingquar", title="Row validation and quarantine (DQ001–DQ006)", milestone="M3",
        area="ingest", agent="codex", size="M", wave=1,
        owns=["src/pulse/ingest/validate.py", "tests/ingest/test_validate.py"],
        context="A vectorized validator (DuckDB SQL or Arrow compute, no per-row Python) that applies rules DQ001–DQ006 from PLAN.md §8 using the contracts. It returns (valid_rows, rejected_rows). Rejected rows carry rule_id, reason and the JSON payload, and are written to quarantine.rejected_rows. Schema drift: a missing required column or type change fails the file; extra columns are logged as WARN and dropped.",
        ac=[
            "On fixtures, quarantined rows equal exactly the DQ001–DQ005 defects in fixtures/defects.json",
            "A file with a missing required column fails with DQ006 and the watermark is unchanged",
            "An extra column produces a WARN row and the file still loads",
            "Validating 100k rows takes < 2 s",
        ],
        verify="uv run pytest tests/ingest/test_validate.py",
        deps=["meta", "contracts", "fixtures"],
    ),
    dict(
        key="ingidem", title="Idempotency and re-run test suite for ingestion", milestone="M3",
        area="ingest", agent="claude", size="M", wave=1,
        owns=["tests/integration/test_idempotency.py", "src/pulse/ingest/__init__.py"],
        context="Wire the loaders and the validator into one `ingest` stage for the runner. Prove the guarantees in PLAN.md §9 with integration tests: double runs, crash in the middle, late-arriving files, and a changed file.",
        ac=[
            "Running ingest twice on the same inputs gives identical raw table hashes and manifest counts",
            "A simulated crash after the activity load but before the client load, followed by a re-run, gives the same final state as a clean run",
            "Late-arriving rows (older activity date, newer extract) are loaded and flagged",
            "The ingest stage is registered in the runner and writes run_log rows",
        ],
        verify="uv run pytest tests/integration/test_idempotency.py",
        deps=["ingactivity", "ingclient", "inghr", "ingquar", "runner"],
    ),
    # ───────────────────────── Wave 1: dbt ─────────────────────────
    dict(
        key="dbtstg", title="dbt staging models (rename, cast, dedupe, normalize postal)", milestone="M4",
        area="dbt", agent="cursor", size="M", wave=1,
        owns=["dbt/models/staging/"],
        context="Build stg_activity, stg_client, stg_advisor, stg_advisor_assignment and stg_branch per PLAN.md §6.6. Dedupe activity by latest updated_ts then _extracted_at. Normalize postal codes to `A1A 1A1`; derive fsa_code or 'UNK'. Compute activity_date with the toronto_date macro, iso_week_id, and is_late_arriving. One .yml per model.",
        ac=[
            "Every column is documented; unique and not_null tests on natural keys",
            "On fixtures, the duplicate defects in defects.json are removed (singular test)",
            "Every postal code variant in fixtures normalizes correctly; invalid ones get 'UNK' (test)",
            "`make dbt-build-ci -s staging` is green",
        ],
        verify="make dbt-build-ci ARGS='-s staging'",
        deps=["dbtscaffold"],
    ),
    dict(
        key="dbtorg", title="dbt dim_org and dim_geography (hierarchy + FSA)", milestone="M2",
        area="dbt", agent="cursor", size="S", wave=1,
        owns=["dbt/models/marts/dim_org.*", "dbt/models/marts/dim_geography.*", "dbt/seeds/"],
        context="dim_org at branch grain with district and region from org.yaml (exported to a dbt seed by `make seeds`). dim_geography at FSA grain: every FSA appearing in branches or clients, plus province and is_rural (second character '0'). Contracts enforced.",
        ac=[
            "dim_org row count equals the branch count in org.yaml; every branch has a district and region",
            "dim_geography includes an 'UNK' member",
            "Relationship tests: dim_org.fsa_code → dim_geography",
        ],
        verify="make dbt-build-ci ARGS='-s dim_org dim_geography'",
        deps=["dbtstg", "orgref"],
    ),
    dict(
        key="dbtscd2", title="SCD2 advisor history and dim_advisor", milestone="M2",
        area="dbt", agent="claude", size="M", wave=1,
        owns=["dbt/models/intermediate/int_advisor_history.*", "dbt/models/marts/dim_advisor.*", "dbt/tests/scd2_*.sql", "docs/adr/0001-scd2-from-events.md"],
        context="Build SCD2 ranges deterministically from assignment events (not dbt snapshot; see PLAN.md §3). valid_to is exclusive; open rows end 9999-12-31; terminations close the last range. Add the Unknown member. Write an ADR explaining why events-based SCD2 is used instead of snapshots for backfill determinism.",
        ac=[
            "Tests: no overlapping ranges per advisor, no gaps between hire and term, exactly one current row for active advisors and none for terminated ones (DQ020)",
            "The two fixture transfers produce exactly two extra rows, with correct dates",
            "advisor_sk is stable across full rebuilds",
            "ADR 0001 is merged",
        ],
        verify="make dbt-build-ci ARGS='-s +dim_advisor'",
        deps=["dbtstg"],
    ),
    dict(
        key="dbtclient", title="dim_client and weekly client book history", milestone="M4",
        area="dbt", agent="cursor", size="M", wave=1,
        owns=["dbt/models/marts/dim_client.*", "dbt/models/intermediate/int_client_book_weekly.*"],
        context="dim_client from stg_client with tenure and age bands. int_client_book_weekly gives client × week with the primary advisor as of week end and an active flag; this is the denominator for coverage.",
        ac=[
            "A fixture client re-assigned mid-period appears under the old advisor before and the new advisor after (test)",
            "Closed clients drop out of the book from the week after closure",
            "Contracts and relationship tests to dim_advisor (by advisor_id, as-of) pass",
        ],
        verify="make dbt-build-ci ARGS='-s +int_client_book_weekly +dim_client'",
        deps=["dbtstg", "dbtscd2"],
    ),
    dict(
        key="dbtfct", title="fct_activity with as-of advisor attribution (incremental)", milestone="M4",
        area="dbt", agent="claude", size="M", wave=1,
        owns=["dbt/models/intermediate/int_activity_enriched.*", "dbt/models/marts/fct_activity.*", "dbt/models/marts/dim_activity_type.*"],
        context="Join each activity to the advisor history row valid at activity_date (branch at the time, not the current branch). Unknown advisors map to the 'UNKNOWN' member. Incremental delete+insert with a 28-day lookback so late arrivals rebuild the affected weeks. Flags: is_completed, is_appointment, is_conversion.",
        ac=[
            "A fixture activity by a transferred advisor is credited to the pre-transfer branch when it predates the transfer (test)",
            "A full refresh and an incremental build give identical results on fixtures (test compares hashes)",
            "A late-arriving fixture row lands in its original week",
            "FK relationship tests to every dimension pass; contract enforced",
        ],
        verify="make dbt-build-ci ARGS='-s +fct_activity' && make dbt-build-ci ARGS='-s fct_activity --full-refresh'",
        deps=["dbtorg", "dbtscd2", "dbtclient"],
    ),
    dict(
        key="dbtweekly", title="mart_advisor_weekly and mart_org_weekly (all hierarchy levels)", milestone="M4",
        area="dbt", agent="cursor", size="M", wave=1,
        owns=["dbt/models/marts/mart_advisor_weekly.*", "dbt/models/marts/mart_org_weekly.*"],
        context="Compute the KPI numerators and denominators from PLAN.md §7 at advisor × week, then roll up to branch, district, region and national with GROUPING SETS. Ratios are computed after roll-up, never averaged. Coverage uses int_client_book_weekly and a trailing 13-week window.",
        ac=[
            "Every KPI in PLAN.md §7 is present, with a column description that quotes its formula",
            "Ratios are recomputed from summed parts (test: national show rate equals the sum of held over the sum of held + no-show)",
            "Coverage for a hand-checked fixture advisor matches the expected value in the test",
            "Contracts enforced",
        ],
        verify="make dbt-build-ci ARGS='-s +mart_org_weekly'",
        deps=["dbtfct"],
    ),
    dict(
        key="dbtreport", title="mart_weekly_report, mart_geo_weekly, mart_dq_weekly", milestone="M4",
        area="dbt", agent="cursor", size="M", wave=1,
        owns=["dbt/models/marts/mart_weekly_report.*", "dbt/models/marts/mart_geo_weekly.*", "dbt/models/marts/mart_dq_weekly.*"],
        context="mart_weekly_report: long format, node × KPI × week with prior week, WoW delta and %, trailing 13-week average, rank within parent, and a flag (ANOMALY when |z| > 2 against the trailing 13 weeks). mart_geo_weekly at FSA × week. mart_dq_weekly from quarantine and staging dedupe counts.",
        ac=[
            "The report has one row per (week, node, KPI); uniqueness test",
            "WoW values are null for the first week and correct afterwards (test on fixtures)",
            "rank_in_parent is dense, 1 = best, with direction per KPI (no-show: lower is better)",
            "mart_dq_weekly counts reconcile with quarantine.rejected_rows",
        ],
        verify="make dbt-build-ci ARGS='-s +mart_weekly_report +mart_geo_weekly +mart_dq_weekly'",
        deps=["dbtweekly"],
    ),
    dict(
        key="dbtkpitests", title="KPI reconciliation tests (children sum to parent)", milestone="M4",
        area="dbt", agent="claude", size="S", wave=1,
        owns=["dbt/tests/reconcile_*.sql", "dbt/macros/test_reconcile.sql"],
        context="A generic test macro: for every additive measure in mart_org_weekly, the sum over children equals the parent at every level and week (DQ022). Ratios stay within [0, 1] (DQ023).",
        ac=[
            "Reconciliation passes on fixtures",
            "Mutating one branch value in a test fixture makes it fail (demonstrated in the PR)",
            "Documented in dbt docs",
        ],
        verify="make dbt-build-ci ARGS='-s test_type:singular'",
        deps=["dbtweekly"],
    ),
    dict(
        key="dbtdocs", title="dbt docs + lineage published as a static site", milestone="M4",
        area="dbt", agent="cursor", size="S", wave=1,
        owns=["scripts/build_dbt_docs.sh", "dbt/models/overview.md"],
        context="Generate dbt docs (static index) as part of export, so they are served at pulse.charliebuild.com/lineage/. Write an overview.md doc block with the layer conventions and a link back to the dashboard.",
        ac=[
            "`make dbt-docs-static` writes web/public/lineage/ containing a working static docs site",
            "The overview page renders project context; lineage graph opens",
            "The folder is gitignored (built in CI)",
        ],
        verify="make dbt-docs-static && python3 -m http.server -d web/public/lineage",
        deps=["dbtscaffold"],
    ),
    # ───────────────────────── Wave 1: geo ─────────────────────────
    dict(
        key="geofsa", title="StatCan FSA boundaries: download, simplify, size budget", milestone="M2",
        area="geo", agent="cursor", size="M", wave=1,
        owns=["geo/", "web/public/geo/", "docs/adr/0002-geo-size-budget.md"],
        context="Script to download the Statistics Canada 2021 FSA boundary file, reproject to WGS84, filter to the FSAs used in org.yaml and the client pool, and simplify with mapshaper to TopoJSON. FSA-level is optional: if it cannot fit within 3 MB gzip at acceptable fidelity, ship only district and region polygons and record that decision in an ADR. Add the Statistics Canada Open Licence attribution.",
        ac=[
            "`make geo` is reproducible from a clean checkout (download cached under data/)",
            "Output size is reported; ≤ 3 MB gzip, otherwise the ADR documents falling back to district level",
            "Attribution text is stored in web/public/geo/ATTRIBUTION.txt",
            "The raw download is not committed",
        ],
        verify="make geo && ls -lh web/public/geo",
        deps=["orgref"],
    ),
    dict(
        key="geodissolve", title="Derive district and region polygons by dissolving FSAs", milestone="M2",
        area="geo", agent="cursor", size="S", wave=1,
        owns=["geo/dissolve.*", "web/public/geo/districts.topo.json", "web/public/geo/regions.topo.json"],
        context="Dissolve FSA polygons into the 14 fictional districts and 4 regions using the org.yaml mapping (each FSA is assigned to the district of its nearest branch). Each feature carries the node_id used in the marts.",
        ac=[
            "14 district and 4 region features, with IDs matching dim_org codes (test)",
            "No slivers larger than a threshold (topology check)",
            "Combined size ≤ 500 KB gzip",
        ],
        verify="make geo && uv run pytest tests/test_geo.py",
        deps=["geofsa"],
    ),
    # ───────────────────────── Wave 1: frontend (on fixtures) ─────────────────────────
    dict(
        key="webdesign", title="Art direction and design system: docs/design.md + chart theme", milestone="M7",
        area="frontend", agent="claude", size="M", wave=1,
        owns=["docs/design.md", "web/src/theme/", "web/src/components/primitives/"],
        context="Define an editorial look that extends charliebuild (paper, ink, signal gold; Avenir Next; mono figures). It should read like a well-made annual report, not a SaaS template. Deliver: type scale, grid, spacing, colour roles, a data palette (sequential from signal, diverging for WoW, status colours for pipeline), motion principles with durations and easings, an ECharts theme object, and primitives (Figure, Stat, Delta, Sparkline wrapper, Breadcrumb, Section).",
        ac=[
            "docs/design.md has rationale plus rules a non-designer agent can follow",
            "Data palette passes WCAG contrast against both backgrounds and works for the common colour-vision deficiencies (checked with a simulator, screenshots in PR)",
            "The ECharts theme is applied globally; primitives render in a /_kitchen-sink dev route in light and dark",
            "Explicit list of banned looks: neon gradients, glassmorphism cards, generic hero-dashboard",
        ],
        verify="make web-dev, then open /_kitchen-sink",
        deps=["webscaffold"],
    ),
    dict(
        key="webdata", title="DuckDB-WASM data layer: manifest, Parquet registration, query hooks", milestone="M7",
        area="frontend", agent="claude", size="M", wave=1,
        owns=["web/src/data/"],
        context="Lazy-load DuckDB-WASM in a worker, fetch manifest.json, register Parquet files over HTTP, and expose typed hooks (useOrgWeekly(nodeId, weeks), useWeeklyReport(...), useGeoWeekly(...), useRunLog(), useNarrative(week, node)). Before DuckDB is ready, render the first paint from a small summary embedded in manifest.json. Verify file sha256 from the manifest. Handle loading, empty and error states.",
        ac=[
            "The overview renders KPI values from the manifest summary before the WASM finishes loading",
            "Query results are typed by the generated contract types",
            "Vitest tests run the hooks against fixtures/exports in Node (duckdb node binding or a mock)",
            "A failed fetch shows a calm error state with the last run time, not a blank page",
        ],
        verify="make web-check && pnpm -C web test",
        deps=["webscaffold", "fixtures"],
    ),
    dict(
        key="webdrill", title="Hierarchy drill-down: National → Region → District → Branch → Advisor", milestone="M7",
        area="frontend", agent="cursor", size="M", wave=1,
        owns=["web/src/features/drill/"],
        context="URL-driven drill (/r/ON/d/GTA/b/BR-0412/a/ADV-00123). Each level shows its KPIs, a ranked list of children with sparklines, and a breadcrumb. Transitions keep spatial context: the clicked row expands into the next view. A week selector is shared via URL.",
        ac=[
            "Every level renders from fixtures; deep links work on a fresh load",
            "The back button and breadcrumb both navigate correctly",
            "Children are sortable by any KPI; keyboard navigable",
            "Works at 375 px",
        ],
        verify="make web-check; Playwright smoke for drill routes",
        deps=["webdata", "webdesign"],
    ),
    dict(
        key="webkpi", title="KPI tiles and trend charts (ECharts)", milestone="M7",
        area="frontend", agent="cursor", size="M", wave=1,
        owns=["web/src/features/overview/"],
        context="Overview: the week's headline KPIs with WoW deltas, 26-week trend lines with a trailing 13-week band, and annotations for ANOMALY flags. All charts use the global theme. Each chart has a text alternative (the summary sentence).",
        ac=[
            "All PLAN.md §7 business KPIs are shown; definitions are available on hover or focus",
            "Charts resize without layout shift; numbers use tabular mono figures",
            "Each chart has an aria-label summary",
        ],
        verify="make web-check",
        deps=["webdata", "webdesign"],
    ),
    dict(
        key="webleader", title="Leaderboard and peer comparison table", milestone="M7",
        area="frontend", agent="cursor", size="S", wave=1,
        owns=["web/src/features/leaderboard/"],
        context="Ranked table of the children of the current node (or advisors within a branch), with KPI selector, rank change vs prior week, and inline sparklines. Uses rank_in_parent from mart_weekly_report.",
        ac=[
            "Rank direction respects the KPI (lower no-show is better)",
            "Virtualized when > 100 rows",
            "Accessible table semantics",
        ],
        verify="make web-check",
        deps=["webdata", "webdesign"],
    ),
    dict(
        key="webmap", title="Geographic view: deck.gl + MapLibre choropleth with drill", milestone="M7",
        area="frontend", agent="cursor", size="M", wave=1,
        owns=["web/src/features/map/"],
        context="Region and district choropleth for the selected KPI and week. Clicking a polygon drills (the same URL state as drill-down). FSA-level coverage heat layer only if FSA boundaries shipped (feature flag from manifest). Basemap: no-key minimal style or none. Show attribution.",
        ac=[
            "Choropleth renders from fixtures with a legend from the data palette",
            "Click and keyboard selection both drill",
            "The FSA layer toggles on only when geo/fsa exists",
            "Map code is lazy loaded (not in the initial bundle)",
        ],
        verify="make web-check",
        deps=["webdata", "webdesign", "geodissolve"],
    ),
    dict(
        key="webnarr", title="Weekly narrative panel with cited facts", milestone="M7",
        area="frontend", agent="cursor", size="S", wave=1,
        owns=["web/src/features/narrative/"],
        context="Render the narrative for the current node and week: headline, bullets, and watchlist. Each bullet can reveal the facts it cites. Label: 'AI-generated from this week's figures'. If fallback is true, label it 'Template summary'.",
        ac=[
            "Renders fixtures/narratives; facts toggle per bullet",
            "Disclosure label is always visible",
            "Hidden gracefully when no narrative exists for the node",
        ],
        verify="make web-check",
        deps=["webdata", "webdesign"],
    ),
    dict(
        key="webdq", title="Data quality page: quarantine and defects by rule over time", milestone="M7",
        area="frontend", agent="cursor", size="S", wave=1,
        owns=["web/src/features/quality/"],
        context="Show mart_dq_weekly: per-rule counts and rates over time, the action taken, and the latest week's check results from run_log. This page shows the data-engineering work directly.",
        ac=[
            "Every DQ rule in PLAN.md §8 is listed, with its action and a short description",
            "Trend per rule; latest-run check results table",
            "Links to the rule definitions in the case study",
        ],
        verify="make web-check",
        deps=["webdata", "webdesign"],
    ),
    # ───────────────────────── Wave 1: pipeline viz ─────────────────────────
    dict(
        key="vizgraph", title="Emit pipeline_graph.json from runner DAG + dbt manifest", milestone="M6",
        area="pipeline-viz", agent="claude", size="S", wave=1,
        owns=["src/pulse/export/pipeline_graph.py", "tests/export/test_pipeline_graph.py"],
        context="Merge the runner's stage DAG with dbt's manifest.json (collapsed to layer-level groups with an expandable model list) into nodes and edges with stable IDs and suggested layout positions.",
        ac=[
            "Output validates against the pipeline_graph contract",
            "Node IDs are stable across runs",
            "dbt nodes are grouped by layer, with model counts",
        ],
        verify="uv run pytest tests/export/test_pipeline_graph.py",
        deps=["runner", "dbtscaffold"],
    ),
    dict(
        key="vizcanvas", title="React Flow pipeline canvas with run replay", milestone="M6",
        area="pipeline-viz", agent="cursor", size="M", wave=1,
        owns=["web/src/features/pipeline/"],
        context="Custom nodes show stage status, rows in/out, quarantined rows, duration and attempts. Edges animate particles in order during a replay of the last weekly run's timeline (compressed to ~6 s), then settle into the final state. A header says 'Replaying weekly run of <date>'. Reduced motion shows the final state with no animation.",
        ac=[
            "Renders fixtures/pipeline_graph.json + run_log.json, including a retried stage and a WARN",
            "Clicking a node opens a side panel with stage details and check results",
            "Replay can be restarted; it is disabled under reduced motion",
            "60 fps on a mid-range laptop (Performance panel screenshot in PR)",
        ],
        verify="make web-check",
        deps=["webscaffold", "webdesign", "fixtures"],
    ),
    dict(
        key="vizhistory", title="Run history strip: last 12 weekly runs", milestone="M6",
        area="pipeline-viz", agent="cursor", size="S", wave=1,
        owns=["web/src/features/pipeline/history/"],
        context="A strip of the last 12 runs (status, duration, rows), with a duration sparkline. Selecting a run replays it on the canvas.",
        ac=[
            "Shows status per run with colour plus an icon (not colour alone)",
            "Selecting a run updates the canvas",
        ],
        verify="make web-check",
        deps=["vizcanvas"],
    ),
    # ───────────────────────── Wave 1: orchestration features ─────────────────────────
    dict(
        key="runchecks", title="Run checks: freshness, volume anomaly, quarantine rate, defect reconciliation", milestone="M5",
        area="orchestration", agent="codex", size="M", wave=1,
        owns=["src/pulse/quality/", "tests/quality/"],
        context="Implement DQ030–DQ033 as a `checks` stage. Each check writes a meta.check_result row. The WARN/FAIL policy is configurable in pulse.toml. Volume uses trailing 8 weeks from mart_org_weekly (national level).",
        ac=[
            "Each check has a passing and a failing unit test",
            "A FAIL check makes the stage FAILED and blocks export",
            "Thresholds come from config, with defaults matching PLAN.md §8",
        ],
        verify="uv run pytest tests/quality",
        deps=["runner", "meta"],
    ),
    dict(
        key="runstate", title="State persistence on R2 with run lock", milestone="M5",
        area="orchestration", agent="claude", size="M", wave=1,
        owns=["src/pulse/state/", "tests/state/"],
        context="restore_state and persist_state stages: sync data/sources and warehouse.duckdb to and from R2 (S3 API via boto3). A lock object with run_id and a 2 h TTL prevents concurrent runs. If the warehouse is missing on restore, trigger a deterministic cold rebuild (backfill) and log it. Tests use moto, with no network.",
        ac=[
            "Restore → run → persist round trip works against moto",
            "A second concurrent run exits SKIPPED while the lock is held; an expired lock is taken over",
            "Missing state triggers the cold-rebuild path (tested with a small week range)",
            "Skips cleanly with a WARN when R2 credentials are absent (local runs)",
        ],
        verify="uv run pytest tests/state",
        deps=["runner"],
    ),
    dict(
        key="runexport", title="Export marts to web Parquet + manifest with size budget", milestone="M5",
        area="orchestration", agent="codex", size="M", wave=1,
        owns=["src/pulse/export/web.py", "tests/export/test_web_export.py"],
        context="Write the files in PLAN.md §6.9 to web/public/data with ZSTD Parquet, row group sizes suited to HTTP range reads, sha256 per file, and a small `summary` block in manifest.json for first paint. Fail if the size budget is exceeded. A failed run exports only run_log.json and keeps existing data files.",
        ac=[
            "Output validates against the export contracts",
            "Total size and per-file size are checked against the budget (test with a tiny budget)",
            "On a failed run, only run_log.json changes (test)",
            "Deterministic file bytes for the same warehouse state",
        ],
        verify="uv run pytest tests/export/test_web_export.py",
        deps=["runner", "fixtures"],
    ),
    dict(
        key="ainarr", title="AI weekly narrative: grounded facts → Anthropic structured output", milestone="M5",
        area="ai", agent="claude", size="M", wave=1,
        owns=["src/pulse/narrative/", "tests/narrative/"],
        context="Build compact fact sets per region and district (PLAN.md §11) from mart_weekly_report, call the Anthropic API (model from PULSE_NARRATIVE_MODEL, default claude-opus-5-5) with a pinned prompt version, and parse a structured JSON response into the narrative contract. Cache by input hash under data/narratives/cache. Tests use a recorded fake client; the `live` marker runs one real call.",
        ac=[
            "Fact builder output is deterministic and covers node, children, and 13-week context",
            "Output validates against the narrative contract; every bullet cites ≥ 1 fact ID",
            "Cache hit means no API call (tested with the fake client)",
            "Without ANTHROPIC_API_KEY the stage writes template narratives and status WARN",
        ],
        verify="uv run pytest tests/narrative -m 'not live'",
        deps=["runner", "fixtures"],
    ),
    dict(
        key="aiguard", title="Narrative guardrails: numeric validator, fallback, eval set", milestone="M5",
        area="ai", agent="claude", size="M", wave=1,
        owns=["src/pulse/narrative/validate.py", "src/pulse/narrative/fallback.py", "tests/narrative/eval/"],
        context="A validator extracts every number and percentage in the text and checks it against the cited facts within rounding tolerance. It also checks banned phrases (speculation about individuals, advice, 'live'). On failure: one regeneration with the validator feedback, then the deterministic template. Eval set: 10 frozen fact sets with expected properties; report pass rates.",
        ac=[
            "The validator catches a fabricated number, a wrong sign on a delta, and an uncited claim (unit tests)",
            "The fallback template is produced for every node when the API is down",
            "`make narrative-eval` prints a pass-rate table (live, manual) and the eval fixtures run offline in CI against recorded outputs",
        ],
        verify="uv run pytest tests/narrative",
        deps=["ainarr"],
    ),
    # ───────────────────────── Wave 2: integration ─────────────────────────
    dict(
        key="runwf", title="weekly.yml and backfill.yml workflows", milestone="M5",
        area="orchestration", agent="cursor", size="M", wave=2,
        owns=[".github/workflows/weekly.yml", ".github/workflows/backfill.yml"],
        context="weekly.yml: cron '0 11 * * 1' plus workflow_dispatch; `concurrency: weekly`; runs `pulse run --week last`, builds the web app, and uploads run artifacts (run_log, check results). backfill.yml: workflow_dispatch with from, to and rebuild inputs. Both read secrets from §13.",
        ac=[
            "A manual weekly run succeeds end to end on the real scale and uploads artifacts",
            "A backfill of 8 weeks succeeds; rebuild=true starts from an empty state",
            "Two dispatched runs at once: the second waits or skips (concurrency + lock)",
            "Job summary shows a stage table with status, rows and duration",
        ],
        verify="gh workflow run weekly.yml && gh run watch",
        deps=["runstate", "runexport", "runchecks", "ingidem", "accounts"],
    ),
    dict(
        key="runalert", title="Alerting: open/update/close a GitHub issue on run failure", milestone="M5",
        area="orchestration", agent="cursor", size="S", wave=2,
        owns=["src/pulse/runner/alert.py", ".github/workflows/weekly.yml (alert step only)"],
        context="On FAIL, open or update a single issue labelled alert:pipeline with a summary table of failing stages and checks and a link to the run. Optional webhook post if ALERT_WEBHOOK_URL is set. On the next SUCCESS, comment and close it.",
        ac=[
            "A forced failure (env PULSE_FORCE_FAIL=checks) opens exactly one issue; a second failure updates it",
            "The next successful run closes it with a comment",
            "No secrets appear in the issue body",
        ],
        verify="Trigger weekly.yml with the force-fail input",
        deps=["runwf"],
    ),
    dict(
        key="rundeploy", title="Deploy to Cloudflare Pages (pulse.charliebuild.com)", milestone="M5",
        area="infra", agent="cursor", size="S", wave=2,
        owns=[".github/workflows/weekly.yml (deploy step)", ".github/workflows/backfill.yml (deploy step)", "web/public/_headers", "web/public/_redirects"],
        context="After a successful run: `wrangler pages deploy web/dist --project-name advisor-pulse`. After a failed run: deploy with only run_log.json updated (the previous data files are restored from the last deployment artifact or R2). Cache headers as in PLAN.md §14.",
        ac=[
            "pulse.charliebuild.com serves the latest week after a manual weekly run",
            "A forced failure redeploys with the old data and a 'last run failed' banner",
            "manifest.json and run_log.json are served with no-cache; hashed assets are immutable",
        ],
        verify="curl -sI https://pulse.charliebuild.com/data/manifest.json",
        deps=["runwf", "webscaffold"],
    ),
    dict(
        key="e2e", title="End-to-end integration: 104-week backfill, fix issues, baseline numbers", milestone="M5",
        area="orchestration", agent="claude", size="M", wave=2,
        owns=["tests/integration/test_e2e.py", "docs/baseline.md"],
        context="Run the full 104-week backfill at default scale, then 2 incremental weeks. Fix integration bugs (or file issues for them), and record baseline numbers: row counts per layer, run duration per stage, export sizes, defect catch rate. These numbers feed the case study.",
        ac=[
            "Backfill + 2 weekly runs complete; all checks pass or WARN with an explanation",
            "Defect reconciliation (DQ033) passes for every week",
            "docs/baseline.md records counts, durations and sizes",
            "A slow-marked e2e test runs 8 weeks at small scale in < 3 min",
        ],
        verify="uv run pytest tests/integration/test_e2e.py -m slow",
        deps=["genincr", "ingidem", "dbtreport", "dbtkpitests", "runchecks", "runexport", "aiguard"],
    ),
    # ───────────────────────── Wave 3: polish ─────────────────────────
    dict(
        key="webmotion", title="Motion pass: week-change tweens, drill transitions, reveals", milestone="M7",
        area="frontend", agent="cursor", size="M", wave=3,
        owns=["web/src/motion/", "web/src/features/*/motion.ts"],
        context="Apply the motion principles from docs/design.md with Motion: number tweens on week change, shared-element drill transitions, staggered section reveals on first view. Everything is disabled or reduced under prefers-reduced-motion.",
        ac=[
            "No layout shift from motion (CLS < 0.05)",
            "Reduced motion removes all non-essential animation (Playwright test with emulation)",
            "Screen recording of the main flows attached to the PR",
        ],
        verify="make web-check",
        deps=["webkpi", "webdrill", "webmap"],
    ),
    dict(
        key="weba11y", title="Performance, accessibility and Playwright smoke suite", milestone="M7",
        area="frontend", agent="claude", size="M", wave=3,
        owns=["web/tests/", "web/lighthouserc.json"],
        context="Enforce the budgets in PLAN.md §12 in CI with Lighthouse CI and a bundle-size check. Playwright smoke on every route in light, dark, reduced motion and 375 px. Fix violations, or file issues for the ones that need larger changes.",
        ac=[
            "Lighthouse a11y ≥ 95 and performance ≥ 85 on overview (CI-enforced)",
            "JS ≤ 350 KB gzip, excluding WASM (CI-enforced)",
            "Playwright smoke passes on all routes and modes",
            "Keyboard-only walkthrough documented in the PR",
        ],
        verify="make web-check",
        deps=["webdrill", "webkpi", "webleader", "webmap", "webnarr", "webdq", "webmotion"],
    ),
    dict(
        key="tabsheets", title="Push the weekly mart to Google Sheets (service account)", milestone="M8",
        area="tableau", agent="codex", size="S", wave=3,
        owns=["src/pulse/export/sheets.py", "tests/export/test_sheets.py"],
        context="A publish_sheets stage writes mart_weekly_report (last 26 weeks) and dim_org to tabs in GSHEET_ID via gspread, replacing contents atomically (write to a temp tab, then rename). It stays well below the Sheets cell limit. Skip with WARN without credentials.",
        ac=[
            "Writes are atomic: a failure mid-write leaves the previous tab intact (tested with a fake client)",
            "Cell count is logged and asserted < 1M",
            "Stage registered in the runner and visible in the pipeline graph",
        ],
        verify="uv run pytest tests/export/test_sheets.py",
        deps=["runexport", "accounts"],
    ),
    dict(
        key="tabworkbook", title="Tableau Public companion workbook with daily sync", milestone="M8",
        area="tableau", agent="human", size="M", wave=3,
        owns=["tableau/README.md", "tableau/screenshots/"],
        context="Build a Tableau Public workbook on the Google Sheet: hierarchy drill with parameter actions, KPI trends, and a district map. Turn on 'Keep this data in sync'. Agents can draft the calculated fields and layout spec in tableau/README.md; Charlie builds and publishes it.",
        ac=[
            "Published on Tableau Public; data sync enabled and verified after one weekly run",
            "tableau/README.md documents calculated fields and the link",
            "Linked from the dashboard footer and the case study",
        ],
        verify="Open the Tableau Public URL after a weekly run and confirm the latest week",
        deps=["tabsheets"],
    ),
    dict(
        key="casestudy", title="Case study page (pulse.charliebuild.com/case-study)", milestone="M8",
        area="docs", agent="claude", size="M", wave=3,
        owns=["docs/case-study.md", "web/src/features/case-study/"],
        context="A narrative for hiring managers: the business problem, architecture (diagram), key decisions with tradeoffs (SCD2 from events, R2 state, DuckDB-WASM, grounded LLM), data-quality approach with real catch-rate numbers from baseline.md, failure handling, the multi-agent build process (issues, waves, tools), and what would change at real scale (Snowflake, Airflow or Dagster, dbt Cloud). Honest that it is a weekly batch on synthetic data.",
        ac=[
            "Every number on the page comes from baseline.md or the latest manifest",
            "Includes the architecture diagram and a link to the lineage site and repo",
            "Reads in ≤ 8 minutes; reviewed by Charlie (approval comment on the PR)",
        ],
        verify="make web-dev, then open /case-study",
        deps=["e2e", "rundeploy"],
    ),
    dict(
        key="readme", title="README, architecture image and demo GIF", milestone="M8",
        area="docs", agent="cursor", size="S", wave=3,
        owns=["README.md", "docs/assets/"],
        context="A repo README that works as a portfolio landing page: one-paragraph pitch, live link, architecture diagram, quickstart, a GIF of drill-down and pipeline replay, and a map of where each concept lives in the code.",
        ac=[
            "Quickstart works from a clean clone in < 5 min",
            "GIF < 5 MB; diagram renders on GitHub",
            "Links to PLAN.md, AGENTS.md, case study and the site",
        ],
        verify="Follow the quickstart on a fresh clone",
        deps=["rundeploy"],
    ),
    dict(
        key="cbentry", title="Add Advisor Pulse to charliebuild.com Selected work", milestone="M8",
        area="docs", agent="cursor", size="S", wave=3,
        owns=["(repo welkincz/charliebuild) index.html project list"],
        context="In the charliebuild repo, add a project entry matching the existing pattern (glyph, name link to https://pulse.charliebuild.com/, tags, kind). Design a glyph that diagrams the project (a hierarchy fanning into a pulse line). Open the PR in welkincz/charliebuild and link it here.",
        ac=[
            "The entry matches the existing markup, tokens and motion; passes that repo's tests",
            "The glyph works in light and dark and under reduced motion",
            "Merged and live on charliebuild.com",
        ],
        verify="python3 -m http.server in the charliebuild repo, then check the project list",
        deps=["casestudy"],
    ),
]


def _numbers() -> dict[str, int]:
    keys = [i["key"] for i in ISSUES]
    assert len(keys) == len(set(keys)), "duplicate issue keys"
    nums = {k: n for n, k in enumerate(keys, start=1)}
    for i in ISSUES:
        for d in i["deps"]:
            assert d in nums, f"{i['key']} depends on unknown {d}"
            assert nums[d] < nums[i["key"]], f"{i['key']} depends on later issue {d}"
    return nums


def _labels(i: dict) -> list[str]:
    status = "status:blocked" if i["deps"] else "status:ready"
    return [f"area:{i['area']}", status, f"size:{i['size']}", f"agent:{i['agent']}", f"wave:{i['wave']}"]


def _milestone_title(key: str) -> str:
    return next(t for k, t, _ in MILESTONES if k == key)


def _deps_text(i: dict, nums: dict[str, int]) -> str:
    return ", ".join(f"#{nums[d]}" for d in i["deps"]) or "none"


def _body(i: dict, nums: dict[str, int]) -> str:
    owns = "\n".join(f"- `{p}`" for p in i["owns"])
    ac = "\n".join(f"- [ ] {a}" for a in i["ac"])
    return f"""## Context
{i['context']}

## Owns (only touch these paths)
{owns}

## Acceptance criteria
{ac}

## Verify
```
{i['verify']}
```

## Dependencies
Depends on: {_deps_text(i, nums)}

---
Size **{i['size']}** · Wave **{i['wave']}** · Suggested agent **{i['agent']}** · Read `AGENTS.md` and `docs/PLAN.md` first.
"""


def render_markdown(nums: dict[str, int]) -> str:
    out = [
        "# Advisor Pulse — Backlog",
        "",
        "> Generated by `scripts/backlog.py`. Edit that file, not this one, then run `python3 scripts/backlog.py`.",
        "",
        f"{len(ISSUES)} issues · {len(MILESTONES)} milestones · sizes S/M only (≤ ~1 agent-day).",
        "",
        "## Waves and parallel lanes",
        "",
        "| Wave | Issues | Max parallel |",
        "|------|--------|--------------|",
    ]
    for w, par in [(0, "2"), (1, "5"), (2, "2–3"), (3, "3")]:
        ids = ", ".join(f"#{nums[i['key']]}" for i in ISSUES if i["wave"] == w)
        out.append(f"| {w} | {ids} | {par} |")
    out += [
        "",
        "Critical path: " + " → ".join(f"#{nums[k]}" for k in ["scaffold", "contracts", "orgref", "fixtures", "meta", "dbtscaffold", "dbtstg", "dbtscd2", "dbtclient", "dbtfct", "dbtweekly", "dbtreport", "e2e", "casestudy", "cbentry"]) + ".",
        "Frontend and pipeline-viz lanes depend only on scaffold, contracts and fixtures, so they run in parallel with the whole backend.",
        "",
        "## Agent load",
        "",
        "| Agent | Issues |",
        "|-------|--------|",
    ]
    for a in ["claude", "cursor", "codex", "human"]:
        ids = ", ".join(f"#{nums[i['key']]}" for i in ISSUES if i["agent"] == a)
        out.append(f"| {a} | {ids} |")
    out.append("")
    for mk, mt, md in MILESTONES:
        out += [f"## {mt}", "", md, "", "| # | Title | Size | Agent | Wave | Depends on |", "|---|-------|------|-------|------|------------|"]
        for i in ISSUES:
            if i["milestone"] == mk:
                out.append(f"| #{nums[i['key']]} | {i['title']} | {i['size']} | {i['agent']} | {i['wave']} | {_deps_text(i, nums)} |")
        out.append("")
    out += ["---", "", "## Issue details", ""]
    for i in ISSUES:
        out += [f"### #{nums[i['key']]} — {i['title']}", "", f"Milestone: {_milestone_title(i['milestone'])} · Labels: {', '.join(_labels(i))}", "", _body(i, nums)]
    return "\n".join(out)


def _sq(s: str) -> str:
    """Single-quote a string for bash."""
    return "'" + s.replace("'", "'\"'\"'") + "'"


def render_shell(nums: dict[str, int]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "# Generated by scripts/backlog.py. Do not edit by hand.",
        "# Creates labels, milestones and the issue backlog in the GitHub repo.",
        "# Requires: gh (authenticated), jq.",
        "# Must run on a repo with no issues or PRs: issue numbers are referenced as dependencies.",
        "set -euo pipefail",
        "",
        f'REPO="${{REPO:-{REPO}}}"',
        "",
        'command -v gh >/dev/null || { echo "gh not found"; exit 1; }',
        'command -v jq >/dev/null || { echo "jq not found"; exit 1; }',
        "",
        'if ! gh repo view "$REPO" >/dev/null 2>&1; then',
        '  echo "Repo $REPO does not exist. Create it first, e.g.:"',
        '  echo "  gh repo create $REPO --public --source=. --push"',
        "  exit 1",
        "fi",
        "",
        'existing=$(gh api "repos/$REPO/issues?state=all&per_page=1" --jq length)',
        'if [ "$existing" != "0" ] && [ "${FORCE:-0}" != "1" ]; then',
        '  echo "Repo already has issues or PRs; numbering would not match. Set FORCE=1 to override."',
        "  exit 1",
        "fi",
        "",
        "echo '==> Labels'",
    ]
    for name, color, desc in LABELS:
        lines.append(f'gh label create {_sq(name)} --repo "$REPO" --color {color} --description {_sq(desc)} --force')
    lines += ["", "echo '==> Milestones'"]
    for _, title, desc in MILESTONES:
        lines += [
            f'if ! gh api "repos/$REPO/milestones?state=all&per_page=100" --jq \'.[].title\' | grep -Fxq {_sq(title)}; then',
            f'  gh api "repos/$REPO/milestones" -f title={_sq(title)} -f description={_sq(desc)} >/dev/null',
            "fi",
        ]
    lines += [
        "",
        "create_issue() {",
        '  local expected="$1" title="$2" milestone="$3" labels="$4" body="$5" url num',
        '  url=$(gh issue create --repo "$REPO" --title "$title" --milestone "$milestone" --label "$labels" --body "$body")',
        '  num="${url##*/}"',
        '  if [ "$num" != "$expected" ]; then',
        '    echo "Expected issue #$expected but got #$num ($url). Stopping so dependencies stay correct."',
        "    exit 1",
        "  fi",
        '  echo "  #$num $title"',
        "}",
        "",
        "echo '==> Issues'",
    ]
    for i in ISSUES:
        lines.append(
            f"create_issue {nums[i['key']]} {_sq(i['title'])} {_sq(_milestone_title(i['milestone']))} "
            f"{_sq(','.join(_labels(i)))} {_sq(_body(i, nums))}"
        )
    lines += ["", f'echo "Done: {len(ISSUES)} issues in $REPO"', ""]
    return "\n".join(lines)


def main() -> None:
    nums = _numbers()
    (ROOT / "docs" / "BACKLOG.md").write_text(render_markdown(nums), encoding="utf-8")
    sh = ROOT / "scripts" / "create_github_backlog.sh"
    sh.write_text(render_shell(nums), encoding="utf-8")
    sh.chmod(0o755)
    print(f"Wrote docs/BACKLOG.md and scripts/create_github_backlog.sh ({len(ISSUES)} issues)")


if __name__ == "__main__":
    main()
