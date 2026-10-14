# Fixtures

Tiny, hand-designed, deterministic datasets for every contract. Build against these before
the generator and the pipeline exist. **Do not edit by hand**: change `src/pulse/fixtures.py`
and run `make fixtures` (a second run is byte-identical; `tests/test_fixtures.py` fails if the
committed files are stale).

## What is in the slice

| | |
|---|---|
| Weeks | 2026-W37 … 2026-W40 (Mon 2026-09-07 … Sun 2026-10-04) |
| Org | 2 regions (ON, QC) · 3 districts (GTA, EON, MTL) · 6 branches from `reference/org.yaml` |
| Advisors | 20 (6 branch managers). In-window events: ADV-10008 GTA→EON (W38), ADV-10004 BR-0101→BR-0102 (W39), ADV-10017 promoted (W40), ADV-10014 terminated (W40) |
| Clients | 200 in the snapshot, 3 added by deltas; ADV-10014's book moves to ADV-10013 on the TERM date |
| Activity | ~160 rows per weekly extract; W40 is split into two part files |

## Layout

```
sources/                        # what upstream drops (paths relative to here in defects.json)
  snowflake/activity/extract_date=YYYY-MM-DD/part-NNN.parquet
  teradata/edw.sqlite           # CLNT, ADVSR, ADVSR_ASGN, BRNCH
  teradata/client_YYYYMMDD.csv  # CLNT deltas (first one has a BOM and quotes every field)
exports/                        # what the export stage writes; web dev serves this as /data
  manifest.json  run_log.json  pipeline_graph.json  narratives/2026-W40.json
  org_weekly.parquet  advisor_weekly.parquet  weekly_report.parquet
  geo_weekly.parquet  dq_weekly.parquet
defects.json                    # ground truth (contract: defect_manifest)
```

## Conventions

- **Extract time.** Each weekly extract is taken Sunday 23:00 America/Toronto, and
  `extract_date` is that Sunday. A row is late when its activity week is earlier than the
  extract's week.
- **Booked meetings.** A `BOOKED` row's `ACTIVITY_TS` is its booking time. When the meeting
  resolves, the re-sent row carries the held (or due) time. `SCHEDULED_TS` never changes.
- **Client snapshot.** `edw.sqlite` CLNT is the state as of 2026-09-06. Every later change is
  in the CSV deltas. The HR tables hold their current state.
- **Effective dates.** Transfers, promotions and the termination take effect on Mondays, so an
  advisor has one branch per week.
- **Unknown advisor.** The `ADV-09999` row is credited to its logged `BRANCH_ID` in
  `org_weekly` and left out of `advisor_weekly`.
- **Row numbers.** `defects.json` rows are 0-based and exclude the CSV header.
- **Late and quarantined rows.** Quarantine defects stay at 2% or less per file, so the DQ032
  circuit breaker does not trip.

## Defects (see `defects.json` for every row)

| Kind | Rule | Where |
|------|------|-------|
| EXACT_DUPLICATE | DQ010 | W37, W39, W40 |
| RESENT_UPDATE | DQ010 | Meetings booked in one extract and resolved in a later one |
| NULL_ACTIVITY_ID | DQ001 | W37 |
| INVALID_ENUM | DQ002 | ACTIVITY_TYPE (W37), STATUS (W38), OUTCOME (W39), CHANNEL (W40) |
| DURATION_OUT_OF_RANGE | DQ003 | W38 |
| ACTIVITY_TS_OUT_OF_RANGE | DQ004 | before 2015 (W39); past extract + 1 day (W40) |
| UNPARSEABLE_VALUE | DQ005 | `client_20260909.csv` (BRTH_YR), `client_20261004.csv` (CLNT_SINCE_DT) |
| UNKNOWN_ADVISOR | DQ012 | W39 |
| DIRTY_POSTAL_CODE | DQ011 | 16 snapshot clients (two of each of 8 variants) plus one delta row |
| LATE_ARRIVING | — | 8 calls delivered 1–3 weeks late |
| ADVISOR_TRANSFER / PROMOTION / TERM | — | ADVSR_ASGN, see above |
| CLIENT_REASSIGNMENT | — | Deltas on 09-13, 09-28 and 10-04 |

## About the exports

The exports are computed from the clean truth with plain Python versions of the KPI rules
(PLAN.md §7). They are internally consistent: children sum to parents, and the manifest's
hashes match. They are fixtures, not the reference implementation; dbt is.

Two simplifications apply because there are only four weeks:

- `trailing_13w_avg` and coverage use whatever history exists.
- `flag = ANOMALY` needs |z| > 3 against the prior weeks and a WoW move of 25% or more.

`run_log.json` holds four runs:

- W37: SUCCESS.
- W38: SUCCESS.
- W39: WARN. The ingest stage fails once and succeeds on the retry, and dbt raises a DQ012 warning.
- W40: WARN, because one narrative fell back to the template.
