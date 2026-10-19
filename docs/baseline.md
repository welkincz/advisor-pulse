# Baseline: 104-week backfill and two weekly runs

These numbers come from a run of the real pipeline at the generator's default scale on synthetic Maplecrest Bank (fictional) data. They are the reference for later performance work and for the case study.

## How it was run

- **Code:** `586f759` (main after #145, #146, #149, #150).
- **Machine:** Apple M4 Max (14 cores, 36 GB), local disk.
- **Environment:** no R2 credentials, so state stayed local. There was no model backend, so every narrative is a template.

```bash
export PULSE_DATA_DIR=run/data PULSE_EXPORT_DIR=run/export
uv run pulse backfill --from 2024-W41 --to 2026-W40 --rebuild
uv run pulse run --week 2026-W41 --run-type WEEKLY
uv run pulse run --week 2026-W42 --run-type WEEKLY
```

- **Backfill:** a cold rebuild of 104 weeks, which took 55.5 minutes of wall time.
- **Weekly runs:** each incremental run took about 37 s.
- **Exit codes:** all three commands exited 0.

## Outcome

| | Runs | Result |
|---|---|---|
| Backfill weeks | 104 | 104 completed, with 0 failed stages |
| Weekly runs | 2 | 2 completed, with 0 failed stages |
| DQ033 defect reconciliation | 106 | 106 PASS ("Missing 0; unexpected 0") |
| DQ030 freshness | 106 | 106 PASS |
| DQ032 load integrity | 106 | 106 PASS |
| DQ031 volume | 106 | 82 PASS, 24 WARN, 0 FAIL |

Every run finishes as WARN, never SUCCESS. Three things cause that, and each one is expected:

| Stage | Status | Why |
|---|---|---|
| `dbt_build` | WARN in all 106 runs | The one warning is the relationship test `stg_activity.booked_from_activity_id → stg_activity.activity_id`, which is set to `severity: warn`. 295 of 68,712 bookings (0.43%) point to a source activity row that DQ001–DQ003 quarantined, so the parent never reaches staging. Keeping the booking is deliberate. |
| `narrate` | WARN in all 106 runs | No model backend was configured, so each week wrote 18 template narratives. The backfill keeps template narratives for historical weeks by design (PLAN.md §9). |
| `checks` | WARN in 24 runs | DQ031, explained below. |

### DQ031 warnings

- **Baseline pending (8 weeks):** 2024-W41 to 2024-W48. These weeks have fewer than 8 reported weeks before them. The partial weeks before the first extract (2024-W38 to W40, which hold only late rows) are excluded since #146.
- **Statutory holidays (10 weeks):**
  - Weeks: 2024-W52, 2025-W21, W27, W36, W40, W52, and 2026-W21, W27, W37, W40.
  - Effect: the generator cuts a holiday's volume to 0.65×, so the week drops 10–17%.
  - Result: that drop is well past 3σ of a steady baseline but far inside the ±50% FAIL bound.
- **Small dips with a narrow baseline (6 weeks):**
  - Weeks: 2025-W18, W19, W20, and 2026-W18, W19, W36.
  - Size: these weeks are 3–5% below the trailing mean.
  - Why they still warn: the trailing σ there is only 119–188 rows, so a 3% dip still crosses 3σ.

The 16 non-pending warnings are 15% of weeks. That is noisy for a check people are meant to look at. A holiday-aware baseline, or a minimum relative change before WARN, would cut most of them. This is a DQ rule change (PLAN.md §8), so it waits for the owner's decision in #156.

## Row counts per layer (after 2026-W42)

| Layer | Table | Rows |
|---|---|---:|
| raw | `snowflake__activity` | 1,535,275 |
| raw | `teradata__clnt` | 184,730 |
| raw | `teradata__advsr` / `teradata__advsr_asgn` | 1,352 / 1,352 |
| raw | `teradata__brnch` | 122 |
| quarantine | `rejected_rows` | 5,906 |
| staging | `stg_activity` | 1,472,505 |
| staging | `stg_client` | 152,234 |
| staging | `stg_advisor` / `stg_advisor_assignment` | 941 / 1,352 |
| intermediate | `int_activity_enriched` | 1,472,505 |
| intermediate | `int_kpi_events` | 18,364,973 |
| intermediate | `int_client_book_weekly` | 20,912,063 |
| intermediate | `int_advisor_history` | 1,311 |
| marts | `fct_activity` | 1,472,505 |
| marts | `dim_client` / `dim_advisor` / `dim_org` | 152,234 / 1,312 / 122 |
| marts | `mart_weekly_report` | 153,902 |
| marts | `mart_advisor_weekly` | 84,795 |
| marts | `mart_org_weekly` | 15,369 |
| marts | `mart_geo_weekly` | 15,172 |
| marts | `mart_dq_weekly` | 848 |
| meta | `run_log` / `load_manifest` / `check_result` | 1,060 / 1,060 / 424 |

### How raw activity becomes staging

| Step | Rows | Change |
|---|---:|---:|
| Raw activity | 1,535,275 | |
| Removed by DQ010 dedupe (exact duplicates and resent updates) | | 56,864 |
| Removed by DQ001–DQ003 quarantine | | 5,906 |
| Staging activity | 1,472,505 | |

- **Weeks in `mart_org_weekly`:** 109, covering 2024-W38 to 2026-W42.
- **The 3 weeks before the first extract** hold late-arriving rows only.

## Duration per stage

### Backfill, 104 weeks

| Stage | Median (s) | p90 (s) | Max (s) | Total (s) |
|---|---:|---:|---:|---:|
| ingest | 15.8 | 17.5 | 135.2 | 1,773 |
| dbt_build | 10.0 | 13.5 | 18.2 | 1,050 |
| generate | 3.0 | 4.0 | 4.2 | 307 |
| export | 1.1 | 1.8 | 2.1 | 111 |
| narrate (template) | 0.2 | 0.2 | 0.2 | 21 |
| checks | 0.1 | 0.2 | 0.2 | 12 |

- **ingest:** the 135 s maximum is the first week, which loads the full client snapshot. After that, ingest is flat at about 16 s per week.
- **dbt_build:** it grows slowly with history, from about 8 s per week early on to about 14 s by 2026.
- **Whole first week:** 145 s. Every week after it takes 41 s or less.

### Weekly runs

| Week | generate | ingest | dbt_build | checks | narrate | export | Rows in → loaded (quarantined) |
|---|---:|---:|---:|---:|---:|---:|---|
| 2026-W41 | 4.4 s | 15.2 s | 13.5 s | 0.2 s | 0.2 s | 1.9 s | 167,034 → 14,564 (55) |
| 2026-W42 | 4.2 s | 14.4 s | 14.9 s | 0.2 s | 0.2 s | 2.0 s | 166,075 → 13,609 (51) |

- **Rows in:** each week ingest reads the week's activity extract plus 8 client delta files, 167,000 rows in all.
- **Rows loaded:** about 14,000 new rows, after the watermark and dedupe.
- **A real weekly run:** this one used templates. The model backend adds about 18 Claude calls for the narratives.

## Export sizes (site after 2026-W42)

| File | Bytes |
|---|---:|
| `weekly_report.parquet` | 2,665,444 |
| `org_weekly.parquet` | 368,936 |
| `advisor_weekly.parquet` | 217,084 |
| `run_log.json` | 67,101 |
| `geo_weekly.parquet` | 17,134 |
| `manifest.json` | 9,545 |
| `pipeline_graph.json` | 6,517 |
| `dq_weekly.parquet` | 6,055 |
| `narratives/*.json` (26 files) | 5,309,257 |
| **Total** | **8,667,073** (43% of the 20 MB budget) |

- **Before #148:** the export had no narrative window. It failed at week 54 of the first attempt with 20,134,747 bytes, against a 20,000,000-byte budget.
- **After #148:** the site keeps the latest 26 weeks of compact narratives, about 200 KB each. Older narratives stay in local storage only, 36 MB for 106 weeks.
- **Local state:** `warehouse.duckdb` is 1.18 GB and the generated sources are 59 MB.

## Defect catch rate

Over 106 weeks the generator injected and recorded these defects. DQ033 compares the manifest with what the pipeline did, week by week. It found no missed and no unexpected rows in any week.

| Defect | Expected action | Rule | Injected |
|---|---|---|---:|
| Null activity id | Quarantine | DQ001 | 2,957 |
| Invalid enum | Quarantine | DQ002 | 1,476 |
| Duration out of range | Quarantine | DQ003 | 1,473 |
| Exact duplicate | Dedupe | DQ010 | 20,498 |
| Resent update | Dedupe | DQ010 | 42,272 |
| Dirty postal code | Normalize | DQ011 | 14,782 |
| Unknown advisor | Map to unknown | DQ012 | 4,415 |
| Late-arriving activity | Keep, flagged | — | 58,719 |

- **Quarantine:** the injected quarantine defects add up to 2,957 + 1,476 + 1,473 = 5,906, exactly the number of rows in `quarantine.rejected_rows`.
- **Change events:** the generator also recorded 31,402 client reassignments and 411 advisor changes (326 transfers, 44 promotions, 41 terminations). These are not defects. They are tested by the SCD2 models, not by DQ033.

## Bugs this run found

| Problem | Fix |
|---|---|
| DQ031 counted the partial weeks before the first extract in its baseline. | Fixed in #146. |
| Unbounded narrative history broke the 20 MB export budget at week 54. | Fixed in #148 (PR #150). |
| CI slowed to 29 minutes once the runner's generate stage used default sizes. | Fixed by small generate sizes in `tests/conftest.py`. |

## Reproducing at small scale

```bash
uv run pytest tests/integration/test_e2e.py -m slow
```

- **What it runs:** an 8-week cold backfill plus one weekly run, at the small sizes from `tests/conftest.py`.
- **Time:** about 85 s.
- **What it asserts:**
  - generate, ingest and dbt_build succeed for every week.
  - DQ030, DQ032 and DQ033 pass every week.
  - The mart holds exactly the expected weeks.
