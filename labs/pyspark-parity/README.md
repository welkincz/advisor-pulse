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

Fixtures hold four weeks of activity, so no week has a full 12-month window and dbt
publishes the rate as null. The published-rate check therefore only proves the null gate
agrees; the unrounded-rate check covers the arithmetic.

## Measured run

Apple M4 Max, local, warm `uv` cache. Output of
`uv run --project labs/pyspark-parity python labs/pyspark-parity/parity.py` (third of three runs):

```text
inputs: raw_client=221, stg_activity=610, stg_portfolio=14, stg_portfolio_assignment=15, dim_activity_type=4, dim_date=1826
spark 4.0.1, local[4], shuffle partitions 4
client-weeks: spark=4549 dbt=4549
branch-weeks: spark=24 dbt=24
wall time: export 0.03s, spark start 2.02s, compute 4.33s, compare 0.37s, total 6.75s
PARITY OK
```

Across three runs the total was 6.75–8.19 s (`time` reported 7.0–8.6 s for the whole
command). On a few thousand rows that is JVM start-up and scheduling overhead, not a
performance result, and it is not a speed comparison with DuckDB.

## Failure tests

`tests/test_parity.py` changes exactly one input row (asserted with `exceptAll`) and
expects parity to fail:

- `test_parity_fails_when_one_client_row_goes_inactive`: one client's only CLNT row gets
  `STAT_CD = 'C'`. Example output: 23 mismatches, including
  `branch-week (2026-W40, BR-0102): spark=(42, 38, 0.9047619047619048, None) dbt=(43, 39, 0.9069767441860465, None)`.
- `test_parity_fails_when_one_contact_is_cancelled`: one completed contact, the client's
  latest that week, becomes `CANCELLED`; the client-week rows for that client no longer match.

```text
labs/pyspark-parity/tests/test_parity.py::test_parity_holds_on_fixtures PASSED
labs/pyspark-parity/tests/test_parity.py::test_parity_fails_when_one_client_row_goes_inactive PASSED
labs/pyspark-parity/tests/test_parity.py::test_parity_fails_when_one_contact_is_cancelled PASSED
labs/pyspark-parity/tests/test_parity.py::test_rate_tolerance_is_tight PASSED
4 passed in 10.96s
```

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
  fixtures (see Parity rule).
- **Not in CI.** The lab runs by hand; the main CI does not install Java or PySpark.
