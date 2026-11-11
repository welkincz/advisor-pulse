# dbt project: `advisor_pulse`

dbt-duckdb models that turn the raw tables into the star schema and weekly marts the web
app reads. Design and column lists: [docs/PLAN.md](../docs/PLAN.md) §6.7–§6.8.

## Running

Run dbt through the Makefile, from the repo root:

| Command | What it does |
|---------|--------------|
| `make dbt-build-ci` | Ingests `fixtures/sources` into `data/ci/warehouse.duckdb` with the real loaders (`scripts/ci_warehouse.py`), loads seeds, then `dbt build --target ci`. CI runs this. Pass `ARGS='-s model+'` to narrow it. |
| `make seeds` | Regenerates `dbt/seeds/*.csv` from `reference/org.yaml` and the shipped FSA boundaries. `make check` fails if those CSVs are stale. |
| `make dbt-docs` | `dbt docs generate` + `serve` against the local `dev` warehouse. |
| `make run WEEK=…` | The weekly pipeline runs dbt against `dev` as one of its stages. |

Targets live in `profiles.yml` (no secrets): `dev` is `$PULSE_DATA_DIR/warehouse.duckdb`,
`ci` is the fixture warehouse. Both pin the DuckDB session to UTC.

## Layers

| Folder | Schema | Materialization | Purpose |
|--------|--------|-----------------|---------|
| `models/staging/` | `staging` | view | One model per source table: rename to `snake_case`, cast, trim, dedupe. No joins. |
| `models/intermediate/` | `intermediate` | table | Business logic: SCD2 advisor history, weekly client book, as-of attribution. |
| `models/marts/` | `marts` | table, **contract enforced** | Star schema (`dim_*`, `fct_*`) and weekly marts (`mart_*`) that the export reads. |

Each folder builds into the schema with the same name (`macros/generate_schema_name.sql`),
so the export can read `marts.mart_org_weekly` directly.

Sources are the warehouse tables in `raw`, `meta` and `quarantine`. `models/sources.yml` is
**generated** from the pydantic contracts by `make contracts`. Do not edit it by hand.
`make contracts-check` fails when it is stale.

## Conventions

- **One `.yml` per model**, next to its `.sql`, with the same name (`dim_date.sql` +
  `dim_date.yml`). Never a shared `schema.yml`. This keeps PRs from different agents from
  conflicting.
- Every model's `.yml` has a description, a description for every column, and tests. Mart
  models also declare `data_type` for every column, because their contract is enforced.
- Timestamps are UTC `TIMESTAMPTZ`. Business dates are America/Toronto: use
  `{{ toronto_date('activity_ts') }}`, never `cast(ts as date)`.
- Weeks are ISO weeks (Monday start): `{{ iso_week_id('d') }}` gives `2026-W40`, and
  `{{ iso_week_start('d') }}` gives that week's Monday. Join weekly marts to `dim_date` on
  `iso_week_id`.
- Keys: `_sk` is a surrogate (hash) key, `_id` is a natural key.
- Generic tests that are not built in live in `macros/tests/` (`iso_week_id_format`,
  `expression_is_true`). Pass their arguments under `arguments:`.
- `tests/assert_date_macros.sql` pins the date macros on DST and ISO-year edge cases.

## Incremental models (#304)

A weekly run keeps history and rebuilds only recent weeks of `fct_activity` and of the
nine `replace_from` models (`macros/weekly_incremental.sql`: the client book, the 12-month
contact window, KPI events and the weekly and quarterly marts).

- **Rebuild floor:** the earlier of four weeks before the newest week a table holds, and
  the earliest day of any raw row loaded since its last runner build. A past-range
  backfill, history extended earlier, or a row later than the lookback rebuilds from its
  own week. `tests/assert_late_rows_within_lookback.sql` warns when a row is that late.
- **Changing a model needs no manual step.** The runner's `dbt_build` stamps each
  incremental table with a fingerprint of its definition and of everything upstream (SQL,
  config, declared columns, project macros, `dbt_project.yml`). On the next run a table
  whose stamp differs is dropped first, so dbt rebuilds it, and everything downstream of
  it, from all history (`src/pulse/runner/refresh.py`). The first run after a deploy
  therefore costs one full build. Description-only edits change nothing.
- **Forcing a full rebuild:** `pulse run --full-refresh`, or the weekly workflow's
  `full_refresh` input; both set `PULSE_DBT_FULL_REFRESH=1` for that run.
- A plain `dbt build` outside the runner reads no stamps: it falls back to the four-week
  lookback, and it never notices a changed definition. Use `--full-refresh` there after
  changing a model.
- `on_schema_change='fail'` stays: a changed column list changes the fingerprint, so the
  table is rebuilt before dbt compares schemas. A mismatch that still reaches dbt is
  unexpected and should stop the run.
