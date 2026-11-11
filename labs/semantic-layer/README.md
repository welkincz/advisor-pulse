# Semantic layer lab (#322)

A small dbt semantic layer (MetricFlow semantic models and metrics) over Advisor Pulse's
KPI building blocks, checked against the published mart. Local, synthetic, single machine.

It answers one question: if the KPIs from [PLAN.md §7](../../docs/PLAN.md) are defined once
as metrics, do the numbers a BI tool would get from them match `mart_org_weekly` at
every level of the org hierarchy?

## Run it

```sh
make dbt-build-ci                                                     # fixture warehouse
uv run --project labs/semantic-layer python labs/semantic-layer/parity.py
uv run --project labs/semantic-layer pytest labs/semantic-layer/tests
```

The lab has its own `pyproject.toml` and `uv.lock` (`dbt-metricflow[dbt-duckdb]`, which
installs dbt-core 1.12.6, dbt-duckdb 1.11.1, MetricFlow 0.15.0 and DuckDB 2.0.0). The root
project, `dbt/dbt_project.yml` and `make check` do not depend on it.

## What is here

| Path | What it does |
|---|---|
| `profiles.yml` | Attaches the main fixture warehouse (`data/ci/warehouse.duckdb`) **read-only** as `pulse`; the lab writes only to its own `target/semantic_lab.duckdb` |
| `models/base/` | `sem_kpi_events` (one row per `int_kpi_events` event, with the week's Monday and the 12-month window flag), `sem_org` (branch → district → region from `dim_org`), and a daily time spine from `dim_date` |
| `models/semantic/semantic_models.yml` | Entities `kpi_event` and `branch`; time dimension `week_start`; additive measures, plus `count_distinct` for clients contacted |
| `models/semantic/metrics.yml` | Five §7 KPIs: the lead KPI `PRTF_CONTACT_12M` (ratio, filtered to weeks with a full 12-month window), `ACT_PER_ADV`, `SHOW_RATE`, `CALLS_OUT`, `CLIENTS_CONTACTED`, and the parts behind them (11 metrics) |
| `parity.py` | Builds the lab, runs one `mf query` per level (national, region, district, branch × ISO week) and compares every value with `mart_org_weekly` at the mart's rounding |
| `models/secure/secure_kpi_events.sql`, `seeds/viewer_scope.csv` | Row-level access **illustration** (below) |
| `tests/test_parity.py` | Parity, three wrong-definition tests, and the row-level illustration |
| `tests/test_full_window.py` | Parity on a backdated copy of the fixture warehouse, where the lead KPI's rate is non-null |

Ratios are metrics over summed numerators and denominators, so MetricFlow rebuilds them at
each grain rather than averaging child ratios, the same rule as the mart's `GROUPING SETS`.
The mart and the semantic layer both read `int_kpi_events`; what is independent is the
aggregation (GROUPING SETS SQL vs MetricFlow-generated SQL).

## Measured run

Apple M4 Max, local, fixtures from `make dbt-build-ci` (4 ISO weeks, 6 branches, 1,623 KPI
events). `parity.py` output:

```
level     mf rows
NATIONAL        4
REGION          8
DISTRICT       12
BRANCH         24
cells compared: 528 (11 metrics)
dbt build (lab): 2.76s
mf query x4 + compare: 5.43s
total wall time: 8.20s
PARITY OK: every MetricFlow value equals mart_org_weekly
```

`pytest labs/semantic-layer/tests`: `6 passed in 42.70s` (each wrong-definition test
copies the project, rebuilds it and reruns all four queries; the full-window test also
rebuilds the main project's mart in a scratch copy).

## The lead KPI with full windows

The fixtures hold four weeks of activity, so no week has a full 12-month window and the
published `portfolio_contacted_rate_12m` is null. `tests/test_full_window.py` copies the
fixture warehouse to a temporary directory, adds 60 completed calls spread back to
January 2025 (the approach of `tests/integration/test_stale_book.py` in #302), rebuilds
`+mart_org_weekly` with the main project's dbt, and runs the same parity check. Every week
from 2026-W01 to 2026-W40 then has a full window: 480 mart rows, 476 with a non-null lead
rate, 5,280 cells compared, and every MetricFlow value equals the mart at its 4-dp
rounding. Pointing the rate's numerator at `activities_completed` on that copy gives 448
mismatches, so the check does see the ratio.

## Failure tests

Each test copies the lab, plants one wrong metric definition and expects the parity check
to name that metric. Mismatch counts from a run on the fixtures:

| Wrong definition | Mismatches | First one reported |
|---|---|---|
| `clients_contacted` uses `count` instead of `count_distinct` | 48 | national 2026-W39: MetricFlow 132 vs mart 92 |
| Lead KPI without the 12-month window filter | 48 | national 2026-W38: MetricFlow 0.6872 vs mart null |
| `show_rate` denominator forgets no-shows | 39 | national 2026-W39: MetricFlow 1.0 vs mart 0.7778 |

## Row-level access illustration (not deployed permissions)

`secure_kpi_events` is a view that returns only the events in the org node a viewer may
read, in the style of BI row-level security. The viewer is a DuckDB session variable and
the scopes are four synthetic personas in `seeds/viewer_scope.csv`:

```sql
SET VARIABLE pulse_viewer = 'dm_gta';            -- district scope
SELECT count(*), count(DISTINCT branch_id) FROM secure_kpi_events;   -- 639 events, 2 branches
```

The test checks that the GTA persona's weekly totals equal the mart's GTA district row,
that the region and branch personas see only their node, and that an unset or unknown
viewer gets zero rows (fail closed).

The same scope as a MetricFlow query filter:

```sh
cd labs/semantic-layer && DBT_PROFILES_DIR=. uv run mf query \
  --metrics calls_out,show_rate,activities_per_advisor,portfolio_contacted_12m,portfolio_clients \
  --group-by metric_time__week,branch__district_code \
  --where "{{ Dimension('branch__district_code') }} = 'GTA'" --order metric_time__week --decimals 4
```

```
metric_time__week    branch__district_code      calls_out    portfolio_contacted_12m    portfolio_clients    show_rate    activities_per_advisor
-------------------  -----------------------  -----------  -------------------------  -------------------  -----------  ------------------------
2026-09-07T00:00:00  GTA                               38                         40                   85       0.8000                    9.0000
2026-09-14T00:00:00  GTA                               37                         57                   85       0.5000                   10.6000
2026-09-21T00:00:00  GTA                               29                         67                   85       0.8750                    9.0000
2026-09-28T00:00:00  GTA                               31                         73                   85       0.7857                   10.6000
```

This is filter logic, not security. Anyone who can open the DuckDB file can read the base
tables; there are no users, grants, identity provider or audit trail.

## Limits

- **No Power BI, DAX, Tableau or other BI tool.** No BI semantic model, no deployed BI
  permissions, no dbt Cloud Semantic Layer API or JDBC endpoint. Queries run through the
  local `mf` CLI only.
- **The lead KPI's non-null rate is checked on backdated data, not on a real year.** On
  the fixtures the rate is null in all four weeks. The full-window test compares non-null
  rates on a copy with 60 calls moved back in time, which is synthetic history, not a
  generated year of activity.
- `CLIENTS_CONTACTED` and `PRTF_CONTACT_12M` are checked by ISO week only. Monthly or
  quarterly roll-ups from MetricFlow were not compared with `mart_org_quarterly`.
- Fixture scale only: 48 mart rows, 528 compared cells. Not run on a full weekly build.
- Row-level access is an illustration with synthetic personas, as described above.
