# Airflow lab: the weekly run as an Airflow DAG

A small, local demonstration for issue #323. The weekly runner's stages
(`src/pulse/runner/dag.py`) become tasks in an Airflow 3.3.2 DAG with a weekly schedule,
retries, timeouts, and a data-interval → ISO-week mapping. The stage code is the project's
own; Airflow schedules and retries it. Synthetic data, one machine, nothing deployed.

## Run it

From the repo root (needs `uv`; the root project must be set up with `make setup`):

```bash
labs/airflow/run_week.sh                                  # one week with `airflow dags test`
uv run --project labs/airflow pytest labs/airflow         # integrity, one-week run, failure test
```

`run_week.sh` creates a throwaway `AIRFLOW_HOME` (SQLite) and `PULSE_DATA_DIR`, migrates the
Airflow DB, and runs `airflow dags test pulse_weekly 2026-11-09T06:00:00+00:00`. Exports go to
`$PULSE_DATA_DIR/web-export`, never to `web/public/data`.

## How it fits together

| Airflow task | Runner stage | Notes |
|---|---|---|
| `pulse_run_id` | (run id) | A new pulse run id for each DagRun, e.g. `manual-2026-W45-airflow-2` |
| `generate` | `generate` | 60 advisors, 1,500 clients (`PULSE_LAB_ADVISORS`, `PULSE_LAB_CLIENTS`) |
| `ingest` | `ingest` | |
| `dbt_build` | `dbt_build` | `dbt build` on the run's DuckDB warehouse |
| `checks` | `checks` | `PULSE_FORCE_FAIL=checks` is the runner's own failure hook |
| `narrate` | `narrate` | Templates only: no model backend, no API key |
| `export` | `export` | `trigger_rule="all_done"`, like the runner's `always=True` |
| `run_status` | (run status) | `one_failed`: turns the Airflow run red when a stage failed |

- **Two environments.** Airflow lives in this lab's own `pyproject.toml`. Each task runs
  `pulse_stage.py` with `uv run --project <repo>`, in the root project's environment. Airflow's
  pins and dbt's pins never share an environment, and the root `uv.lock` is unchanged.
- **Left out:** the R2 state stages (`restore_state`, `persist_state`, `release_lock`). The lab
  keeps its state in a local directory.
- **Run log.** `pulse_stage.py` writes each attempt to `meta.run_log`, using Airflow's try
  number as the attempt. Retries therefore show up in `run_log.json` as well as in Airflow.
- **One pulse run id per DagRun.** The first task numbers a new id after the ids already in
  `meta.run_log`, as the runner does. Retries and cleared tasks in that DagRun reuse it
  through XCom. A new DagRun for the same week gets the next number. With one id per week,
  a re-run after a failed week would start again at try 1, the failed run's attempts 2
  and 3 would outrank it, and the week would stay FAILED with no data exported. The tests
  re-run a failed week and check for this.
- **Why `run_status` exists.** Airflow decides a run's state from its leaf tasks. Without
  `run_status`, `export` (which runs after any outcome) succeeds, and a failed week would end
  green. The failure test caught this.

## Schedule, data interval and backfill

- `CronDataIntervalTimetable("0 6 * * 1", UTC)`: the run fires Monday 06:00 UTC. Its data
  interval runs from the previous Monday 06:00 to this Monday 06:00.
- The ISO week is the week that contains the interval's start, so a Monday run reports the
  week that just ended, the same week as `pulse run --week last`. A manual
  `airflow dags test pulse_weekly <date>` reports the last full week before `<date>`.
  The tests cover the 2026-W53 → 2027-W01 boundary.
- `catchup=False`: turning the DAG on does not queue every week since 2024-W41.
  `airflow backfill create --from-date … --to-date …` creates one run per interval, one ISO
  week each (tested from the timetable: 2026-10-05 to 2026-11-02 gives W41 to W45).
- `max_active_runs=1`: weeks share one warehouse and SCD2 history, so one week runs at a
  time, in order. `pulse_run_id` has `depends_on_past=True` and `wait_for_downstream=True`,
  so a week starts only after the previous week's run finished cleanly: every stage and
  `run_status` succeeded or was skipped. A failed week blocks the next one until it is
  re-run or marked done. The tests check these settings; `dag.test()` does not run a
  scheduler, so the blocking itself is not exercised here.
- The project's own `pulse backfill` is faster for many weeks because it finalizes once
  (#275). An Airflow backfill runs the full DAG for every week.
- Retries: 2 per task, exponential backoff starting at 5 min (1 s in tests).
  `execution_timeout` is 30 min per task, and `dagrun_timeout` is 2 h per run.
- SLAs: Airflow 3 removed `sla=` and `sla_miss_callback`. Timeouts are the bound used here.
  Deadline Alerts (3.1+) need a running scheduler and triggerer, so this lab does not use them.

## Pinned dependencies and the constraints file

Airflow should be installed with its constraints file. `uv lock` has no `--constraint`
flag, so `pin_constraints.py` copies the official
[`constraints-3.3.2/constraints-3.12.txt`](https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt)
pins into `[tool.uv] constraint-dependencies`. It writes only the 125 packages in this lock.
Before this step, an unconstrained resolve drifted on 70 packages, for example
SQLAlchemy 2.1.8 instead of 2.0.52 and python-dateutil 4.0.0 instead of 2.9.0.post0.
`apache-airflow-core`, `apache-airflow-task-sdk` (they follow the pinned `apache-airflow`)
and `pytest` (dev only) are not in that file.

## Measured run

Apple M4 Max, local, 2026-11-11. ISO week 2026-W45.

`labs/airflow/run_week.sh`:

```
{"stage": "allocate", "week": "2026-W45", "run_id": "manual-2026-W45-airflow-1"}
{"stage": "generate", ..., "status": "SUCCESS", "message": "2026-W45: generated with 209 recorded defects."}
{"stage": "ingest", ..., "status": "SUCCESS", "rows_out": 49262, ...}
{"stage": "dbt_build", ..., "status": "WARN", "rows_out": 529, "message": "529 dbt nodes; 1 warned: dq025_portfolio_holder_at_another_branch.4e261280ed."}
{"stage": "checks", ..., "status": "WARN", "message": "DQ031 WARN"}
{"stage": "narrate", ..., "status": "WARN", "rows_out": 23, "message": "No model backend configured: wrote 23 template narratives."}
{"stage": "export", ..., "status": "SUCCESS", "rows_out": 9, "message": "Exported 9 files for 2026-W45."}
DagRun Finished: dag_id=pulse_weekly, logical_date=2026-11-09 06:00:00+00:00, ... state=success
wall time: 17.9 s (airflow dags test, incl. CLI start-up)
```

Stage durations from `run_log.json`: generate 0.8 s, ingest 2.3 s, dbt_build 9.6 s,
checks 0.1 s, narrate 0.05 s. That is about 12.8 s of stage work. The other ~6 s is Airflow
start-up, task scheduling and one `uv run` process per task. WARN is a stage outcome the
runner reports. Airflow treats it as success.

`uv run --project labs/airflow pytest labs/airflow -s` (16 passed in 66.5 s):

```
manual__2026-11-09T06:00:00+00:00: success in 16.1 s
  pulse_run_id and the six stages                        success  try 1
  run_status                                             skipped
manual__2026-11-09T06:00:00+00:00: failed in 17.7 s     (PULSE_FORCE_FAIL=checks)
  checks     failed           try 3
  narrate    upstream_failed  try 0
  export     success          try 1     publishes run_log.json only
  run_status failed           try 1
manual__2026-11-09T06:00:00+00:00: failed in 17.6 s     (re-run test: fail first ...)
manual__2026-11-09T06:00:00+00:00: success in 10.5 s    (... then re-run the week clean)
```

The failure test also asserts that `run_log.json` holds `checks` attempts 1, 2 and 3 as
FAILED, no `narrate` row, and no new data manifest. The re-run test fails a week, then
runs it again clean on the same data dir: the Airflow run succeeds, `run_log.json` leads
with `manual-2026-W45-airflow-2` (WARN, from the DQ warnings) above `-airflow-1` (FAILED),
and the manifest and narratives are written. The integrity test reads the runner's
`execution_order(WEEKLY_STAGES)` from the root environment and fails if the task order,
upstream sets or `always` → `all_done` mapping drift from it.

## Limits

- Local and standalone: `airflow dags test` / `dag.test()` on SQLite, one process. There is
  no deployed scheduler, webserver, workers, Celery or Kubernetes executor, and no Postgres
  metadata DB.
- No history of scheduled runs, SLA or deadline alerting, pools, or on-call. The weekly
  report in production still runs on GitHub Actions (`.github/workflows/weekly.yml`), not on
  Airflow.
- Small synthetic world (60 advisors, 1,500 clients, one week). This is not employer-scale,
  production or regulated experience.
- A task killed by `execution_timeout` can leave its `run_log` row in RUNNING: the stage
  process may never write its end row. Airflow still marks the task failed and retries it.
- Not part of `make check` or CI. The root project does not depend on Airflow.
