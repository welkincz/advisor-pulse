# PySpark parity lab

A local-mode PySpark rebuild of one dbt computation: the lead KPI, **portfolio contacted in
the last 12 months**, by branch and week, as published in `mart_org_weekly` (BRANCH rows).
It starts from the same inputs dbt reads on fixtures and checks that both engines agree.
Synthetic data, one machine, local mode. It does not show cluster, Databricks or
production Spark experience.

## Run it

From the repo root (needs Java 17 or 21; this machine has Oracle JDK 21.0.1):

```bash
make dbt-build-ci                                                      # dbt on fixtures -> data/ci/warehouse.duckdb
uv run --project labs/pyspark-parity python labs/pyspark-parity/parity.py   # rebuild + parity check
uv run --project labs/pyspark-parity pytest labs/pyspark-parity             # parity and failure tests
```

The lab has its own `pyproject.toml` and `uv.lock` (`pyspark==4.0.1`, `duckdb`, `pytest`).
None of it is in the root project, and `make check` does not need it. Spark 4 runs on
Java 17 or 21; `java -version` must find one, or set `JAVA_HOME`.

## What it rebuilds

| dbt model | Spark function | DataFrame technique |
|---|---|---|
| `int_portfolio_history` | `portfolio_history` | `row_number` for same-day ties, `lead` for SCD2 `valid_to` |
| `int_client_book_weekly` (the parts the KPI uses) | `client_versions`, `client_contact_12m` | `row_number` dedupe of reloads, `lead` ranges, broadcast range join to the week cut-off (Sunday 23:59 America/Toronto) |
| `int_client_contact_12m` | `client_contact_12m` | DuckDB's `ASOF` join rebuilt as a union of book and contact rows, `repartition(4, "client_id")`, then `last(..., ignorenulls)` over a running window |
| `int_contact_window` | `contact_window` | window completeness and reported weeks |
| `mart_org_weekly` portfolio columns, BRANCH level | `branch_weekly` | `groupBy` on week and transit branch; rate from summed parts, rounded to 4 dp only when the window is complete |

Inputs, exported from the CI warehouse as Parquet: `raw.teradata__clnt` (221 rows),
`staging.stg_activity` (610), `staging.stg_portfolio` (14),
`staging.stg_portfolio_assignment` (15), `marts.dim_activity_type` (4), `marts.dim_date` (1,826).

Partitioning is set, not left to defaults: `local[4]`, `spark.sql.shuffle.partitions=4`,
AQE off so the plan is the same every run, small sides broadcast explicitly, and one
explicit repartition by `client_id` before the as-of window.

## Parity rule

`parity.py` compares two levels against the dbt tables:

- **Client × week** (`int_client_contact_12m`, 4,549 rows): every column must match exactly
  (portfolio, holder, transit branch, last contact date, contacted flag). A row on one side only fails.
- **Branch × week** (`mart_org_weekly`, 24 rows): `portfolio_clients` and
  `portfolio_contacted_12m` must match exactly; the unrounded rate and the published
  `portfolio_contacted_rate_12m` must agree within 1e-9 (null must match null).

Fixtures hold four weeks of activity, so no week has a full window and dbt publishes the
rate as null. `tests/test_full_window.py` backdates contacts on a scratch copy so the
published rate, its gate and the first reported week meet real values (see Failure tests).

## Measured run

Apple M4 Max, local, warm `uv` cache. Output of
`uv run --project labs/pyspark-parity python labs/pyspark-parity/parity.py` (one run after the review fixes):

```text
inputs: raw_client=221, stg_activity=610, stg_portfolio=14, stg_portfolio_assignment=15, dim_activity_type=4, dim_date=1826
spark 4.0.1, local[4], shuffle partitions 4
client-weeks: spark=4549 dbt=4549
branch-weeks: spark=24 dbt=24 (published rates: 0)
wall time: export 0.03s, spark start 2.17s, compute 3.86s, compare 0.34s, total 6.40s
PARITY OK
```

Across four runs the total was 6.40–8.19 s (`time` reported 7.0–8.6 s for the whole
command on the first three). On a few thousand rows that is JVM start-up and scheduling overhead, not a
performance result, and it is not a speed comparison with DuckDB.

## Failure tests

`tests/test_parity.py` changes exactly one input row (asserted with `exceptAll`) and
expects parity to fail:

- `test_parity_fails_when_one_client_row_goes_inactive`: one client's only CLNT row gets
  `STAT_CD = 'C'`. Example output: 23 mismatches, including
  `branch-week (2026-W40, BR-0102): spark=(42, 38, 0.9047619047619048, None) dbt=(43, 39, 0.9069767441860465, None)`.
- `test_parity_fails_when_one_contact_is_cancelled`: one completed contact, the client's
  latest as of 2026-W40, becomes `CANCELLED`; the client-week rows for that client no longer match.

```text
labs/pyspark-parity/tests/test_full_window.py::test_parity_holds_with_published_rates PASSED
labs/pyspark-parity/tests/test_parity.py::test_parity_holds_on_fixtures PASSED
labs/pyspark-parity/tests/test_parity.py::test_parity_fails_when_one_client_row_goes_inactive PASSED
labs/pyspark-parity/tests/test_parity.py::test_parity_fails_when_one_contact_is_cancelled PASSED
labs/pyspark-parity/tests/test_parity.py::test_rate_tolerance_is_tight PASSED
5 passed in 15.28s
```

`tests/test_full_window.py` covers what the fixtures cannot. It copies the CI warehouse to
a temp dir, adds 60 completed calls spread from 2025-02-01 (the approach of the
stale-book test in #364), reruns `dbt run --select +mart_org_weekly` on the
copy with the root venv, and checks parity there. The window is first complete in
2026-W05, so book weeks W01–W04 exist but are not reported, and the published rate is
non-null (and differs from the unrounded rate) on many branch-weeks. Removing the 4-dp
rounding or the first-reported-week rule from `parity.py` makes it fail. It skips when the
root venv (`make setup`) is missing.

## Limits

- **Local mode only.** One JVM on one laptop; no cluster, no executors on other machines,
  no shuffle across a network.
- **No Databricks**, no Unity Catalog, no jobs or workflows, no managed runtime.
- **No cluster tuning.** Partition counts are sized for a few thousand rows; nothing here
  was measured at scale, and no skew, spill or memory tuning was needed or done.
- **No Delta Lake** (or Iceberg/Hudi). Inputs are plain Parquet exported from DuckDB; there
  is no medallion layout, `MERGE`, time travel or table maintenance.
- **One KPI, not the pipeline.** Only the portfolio columns of the BRANCH rows are rebuilt.
  The other mart columns, the region/district/national roll-ups and the weekly runner stay in dbt.
- **Fixture scale.** 221 raw client rows and 610 activities; the rate itself is null on
  fixtures, and non-null only in the backdated copy (60 added contacts).
- **Not in CI.** The lab runs by hand; the main CI does not install Java or PySpark.
