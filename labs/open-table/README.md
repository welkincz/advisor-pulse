# Open table format lab (Apache Iceberg)

A small, local exercise for issue #325. It writes the `advisor_weekly` mart from the project's
deterministic fixture (`fixtures/exports/advisor_weekly.parquet`, Maplecrest Bank (fictional),
synthetic) into an Apache Iceberg table, one ISO week per commit. It is a lab beside the weekly
report, not part of it: the pipeline, `make check` and the root `pyproject.toml` do not use it.

```bash
uv run --project labs/open-table python labs/open-table/open_table.py   # demo
uv run --project labs/open-table pytest labs/open-table -q               # tests
```

## What it shows

| Step | How |
|---|---|
| Append per ISO week | Identity partition on `iso_week_id`; one `write_week` call per week |
| Idempotent re-run | `dynamic_partition_overwrite` replaces the week's partition: delete and append commit together in one metadata update, so a re-run never duplicates rows |
| Schema evolution | `update_schema().add_column("loaded_by_run", string)`; older rows read back as null |
| Time travel | `scan(snapshot_id=...)` on the snapshot before the re-run and schema change returns the old 17 columns |
| Read with DuckDB | DuckDB's `iceberg` extension, `iceberg_scan(<current metadata.json>)` |

## Why Iceberg, not Delta

The competency this lab answers is tagged `iceberg` in `docs/reviewer-skills.json`; Delta Lake
sits with the Spark/Databricks gap (#321). pyiceberg also gives a real catalog (SQLite via
SQLAlchemy), so the commit, snapshot and metadata-file model is visible, not just a folder of
Parquet with a log.

## Tests (`tests/test_open_table.py`)

- Same week written twice: same row count (27) and same content hash.
- A re-run with fewer rows replaces the week rather than merging into it.
- Failure: a multi-week batch is refused before any commit.
- Failure: changing `activities_completed` from long to string is rejected
  (`ValidationError`) and the schema is unchanged.
- Failure: writing a frame whose `activities_completed` is a string is rejected and no snapshot
  is created.
- Time travel to the snapshot before evolution returns the old rows and schema.
- The full demo reads back 55 rows through DuckDB. This one test needs network the first time,
  to download DuckDB's `iceberg` extension. Offline with an empty extension cache, it **skips**
  and gives the reason. A separate test checks that an unreachable extension repository produces
  that skip reason.

Replacing `dynamic_partition_overwrite` with a plain `append` fails four of the eight tests,
which is the duplicate-row bug the overwrite exists to prevent.

## Measured run

Apple M4 Max, local SSD, pyiceberg 0.12.0, DuckDB 2.0.0, pyarrow 26.0.1, 2026-11-11.

```text
source_rows: 55
weeks: ['2026-W37', '2026-W38', '2026-W39', '2026-W40']
rows_after_appends: 55
rows_after_rerun: 55
hash_after_appends: e8647bb683cf7ae8
hash_after_rerun: e8647bb683cf7ae8
rows_after_evolution: 55
columns_now: 18
null_loaded_by_run: 42
time_travel_rows: 55
time_travel_columns: 17
time_travel_hash: e8647bb683cf7ae8
metadata_commits: 9
duckdb_week_counts: [('2026-W37', 14), ('2026-W38', 14), ('2026-W39', 14), ('2026-W40', 13)]
timings_s: {'setup_s': 0.036, 'append_weeks_s': 0.055, 'rerun_week_s': 0.016,
            'evolve_and_write_s': 0.023, 'time_travel_s': 0.004, 'duckdb_read_s': 0.044,
            'total_s': 0.192}
```

`uv run` wall time for the whole demo was 0.54 s warm. The first run in a new environment
reported `total_s: 4.162` (cold caches). DuckDB needs network once to download its `iceberg`
extension. Snapshot IDs are random per
run; the content hash is deterministic. Nine metadata commits: create, partition spec, four
weekly appends, the re-run, the schema change, and the evolved write. The timings measure
commit overhead on 55 rows. They say nothing about behaviour at volume.

## Limits

- Local filesystem warehouse and a SQLite catalog. No object store (S3/R2/GCS), no REST, Glue,
  Nessie or Polaris catalog.
- One writer. No concurrent writers, so optimistic-concurrency conflicts and retries are not
  exercised.
- No compaction, snapshot expiry, orphan-file cleanup, or row-level deletes / merge-on-read.
- Synthetic fixture of 55 rows; no performance claim at scale.
- Streaming is deliberately excluded. Advisor Pulse is a weekly batch report, so Kafka, Flink
  or Spark Structured Streaming would add a runtime with nothing to consume it. No streaming
  experience is claimed.
