# Baseline: the 106-week rebuild

These numbers come from the last full rebuild of the real pipeline at the generator's default scale on synthetic Maplecrest Bank (fictional) data, with the one-year warm-up added in #273. They are the reference for later performance work and for the case study. Every figure names its source.

## Sources

| Source | What it is |
|---|---|
| Run [40047052218](https://github.com/welkincz/advisor-pulse/actions/runs/40047052218) | `backfill.yml` with `rebuild=true`, 2024-W41 to 2026-W42, code `ef841e1`. It stopped on the time budget after 77 weeks. |
| Run [40065355219](https://github.com/welkincz/advisor-pulse/actions/runs/40065355219) | The continuation it dispatched, 2026-W14 to 2026-W42. It built and deployed the site. |
| Artifact `pages-deploy-40065355219` | The deployed site, including `data/manifest.json`, the Parquet exports and `run_log.json`. |
| Artifact `backfill-40065355219` | `run_log.json` with stage timings and row counts for the last 12 weeks. |
| Local reproduction | The same code and seed on an Apple M4 Max with no R2 credentials and no model backend (commands below). It gives the warehouse row counts, which the Actions runs do not upload. Its `mart_dq_weekly` and `mart_org_weekly` match the deployed exports row for row, so the counts are the deployed run's counts. |

```bash
export PULSE_DATA_DIR=run/data PULSE_EXPORT_DIR=run/export   # the export dir must not exist yet
uv run pulse backfill --from 2024-W41 --to 2026-W42 --rebuild
```

The weekly reports that ran before #273 (`weekly.yml`) used the old generator, so none of them is a source here. This rebuild includes the #288 change to who gets contacted: the national 12-month contacted rate now rises from 82.9% in 2024-W41 to 86.4% in 2026-W42, by at most 0.09 points a week. That change moves contacts between clients, not their number, so every row and defect count below is the same as in the rebuild before it.

## Outcome

From the step logs of both runs (`gh run view <id> --log`):

| | Result |
|---|---|
| Weeks | 106, 2024-W41 to 2026-W42 (`weeks_available` in `manifest.json`) |
| Runs | 97 SUCCESS, 9 WARN, 0 failed stages, 0 retries |
| `checks` | WARN in 8 runs (2024-W41 to W48), SUCCESS in 98 |
| `dbt_build` | "527 dbt nodes passed" in all 106 runs |
| `narrate` | Templates for the 105 historical weeks. In 2026-W42 the model wrote 25 of 27 narratives; 2 failed validation and fell back to the template, which made that run WARN. |

- **The 8 check warnings** are DQ031 with a pending baseline: those weeks have fewer than 8 reported weeks before them. DQ030, DQ032 and DQ033 passed in every run.
- **DQ033 defect reconciliation** passed in all 106 weeks: "Missing 0; unexpected 0". The local reproduction agrees: 106 PASS for DQ030, DQ032 and DQ033.

## Row counts per layer (after 2026-W42)

From the local reproduction's `warehouse.duckdb`.

| Layer | Table | Rows |
|---|---|---:|
| raw | `snowflake__activity` | 2,265,315 |
| raw | `teradata__clnt` | 288,487 |
| raw | `teradata__advsr` / `teradata__advsr_asgn` | 1,371 / 1,577 |
| raw | `teradata__prtf` / `teradata__prtf_asgn` | 1,320 / 2,049 |
| raw | `teradata__brnch` | 122 |
| quarantine | `rejected_rows` | 5,910 |
| staging | `stg_activity` | 2,202,422 |
| staging | `stg_client` | 153,338 |
| staging | `stg_advisor` / `stg_advisor_assignment` | 962 / 1,577 |
| intermediate | `int_activity_enriched` | 2,202,422 |
| intermediate | `int_kpi_events` | 17,961,907 |
| intermediate | `int_client_book_weekly` | 25,243,626 |
| intermediate | `int_client_contact_12m` | 22,194,794 |
| intermediate | `int_advisor_history` | 1,515 |
| marts | `fct_activity` | 2,202,422 |
| marts | `dim_client` / `dim_advisor` / `dim_org` | 153,338 / 1,516 / 122 |
| marts | `mart_weekly_report` | 159,212 |
| marts | `mart_portfolio_weekly` | 120,901 |
| marts | `mart_advisor_weekly` | 82,468 |
| marts | `mart_org_weekly` | 15,900 |
| marts | `mart_geo_weekly` | 14,734 |
| marts | `mart_org_quarterly` | 1,350 |
| marts | `mart_dq_weekly` | 954 |

### How activity rows become staging

| Step | Rows | Change |
|---|---:|---:|
| Activity rows read (158 extract files, `load_manifest.row_count`) | 2,271,225 | |
| Quarantined by DQ001–DQ003, never loaded to raw | | 5,910 |
| Loaded to `raw.snowflake__activity` | 2,265,315 | |
| Collapsed by DQ010 dedupe (exact duplicates and resent updates) | | 62,893 |
| Staging activity | 2,202,422 | |

- **Warm-up year:** 727,378 of the rows read come from the 52 clean warm-up extracts that the first week loads (#273), so the 12-month contacted rate has a full window from 2024-W41. They are loaded, never reported.
- **Reported weeks:** the other 1,543,847 rows belong to the 106 reported weeks. That is the sum of `rows_in_batch` in the deployed `dq_weekly.parquet`, and 1,475,044 of them are kept.

## Duration

### The rebuild on GitHub Actions

| | Wall time | Weeks |
|---|---:|---:|
| Run 40047052218 (00:51 to 05:12 UTC) | 4 h 21 min | 77, then "Time budget reached after 77 weeks (260 min of 320 min)" |
| Run 40065355219 (05:12 to 07:13 UTC) | 2 h 01 min | 29, then the site build and deploy |
| **Whole rebuild** | **6 h 22 min** | **106** |

Per week, from the `Backfill n/106` timestamps in the logs:

- **First week:** 48.8 minutes. It generates and loads the warm-up year as well as its own week.
- **Later weeks:** 136 s at 2024-W42, growing to about 195 s by 2026-W12. In the second run the first week took 506 s and the rest 205–235 s.
- **Last week:** 668 s, because it was the only week that called the model.

**Why it is slow.** A backfill replays the whole weekly pipeline once per week: each week runs a full `dbt build` over all the history so far and persists the warehouse to R2, so the cost grows with every week added. #275 runs dbt, checks, export and persist once per backfill instead of once per week, and will update these figures when it lands.

### One week

The stages of `backfill-2026-W42-1` and the median of the last 12 weeks, from `run_log.json` in artifact `backfill-40065355219`. A weekly report runs the same stages.

| Stage | 2026-W42 (s) | Median, last 12 weeks (s) |
|---|---:|---:|
| restore_state | 23 | 23 |
| generate | 20 | 19 |
| ingest | 34 | 36 |
| dbt_build | 113 | 108 |
| checks | 1.0 | 1.0 |
| narrate | 426 (model) | 0.8 (template) |
| export | 5 | 5 |
| persist_state | 45 | |
| **Whole run** | **668** | |

- **Without the model:** about 4 minutes (median 227 s), most of it dbt.
- **With the model:** about 11 minutes. Narration is 27 Claude calls, one per region and district.
- **Ingest in 2026-W42:** 170,990 rows read (the week's activity extract plus 8 client delta files), 13,815 loaded, 52 quarantined.

## Export sizes (site after 2026-W42)

From the deployed site in `pages-deploy-40065355219`; the bytes match `manifest.json`.

| File | Bytes |
|---|---:|
| `weekly_report.parquet` | 2,785,756 |
| `org_weekly.parquet` | 372,745 |
| `portfolio_weekly.parquet` | 262,875 |
| `advisor_weekly.parquet` | 239,857 |
| `org_quarterly.parquet` | 69,853 |
| `run_log.json` | 63,569 |
| `geo_weekly.parquet` | 20,243 |
| `manifest.json` | 9,851 |
| `dq_weekly.parquet` | 6,742 |
| `pipeline_graph.json` | 6,069 |
| `narratives/*.json` (26 files, 2026-W17 to W42) | 6,647,405 |
| **Total** | **10,484,965** (52% of the 20 MB budget) |

- **Narratives:** the site keeps the latest 26 weeks, about 255 KB each (#148). Older narratives stay in state only: 43 MB for 106 weeks in the local reproduction.
- **Local state:** `warehouse.duckdb` is 1.7 GB and the generated sources are 84 MB. The local reproduction took 95 minutes of wall time.

## Defect catch rate

Over the 106 reported weeks the generator injected and recorded these defects (`defects.json` in the local reproduction). The warm-up extracts are clean. DQ033 compares the manifest with what the pipeline did, week by week, and found no missed and no unexpected rows in any week.

| Defect | Expected action | Rule | Injected |
|---|---|---|---:|
| Null activity id | Quarantine | DQ001 | 2,960 |
| Invalid enum | Quarantine | DQ002 | 1,476 |
| Duration out of range | Quarantine | DQ003 | 1,474 |
| Exact duplicate | Dedupe | DQ010 | 20,541 |
| Resent update | Dedupe | DQ010 | 42,352 |
| Dirty postal code | Normalize | DQ011 | 23,069 |
| Unknown advisor | Map to unknown | DQ012 | 4,430 |
| Unknown portfolio | Map to unknown | DQ014 | 399 |
| Late-arriving activity | Keep, flagged | — | 58,824 |

- **Quarantine:** 2,960 + 1,476 + 1,474 = 5,910, exactly the rows in `quarantine.rejected_rows`.
- **Dedupe:** 20,541 + 42,352 = 62,893, exactly the rows DQ010 collapsed.
- **Change events:** the generator also recorded 31,184 client reassignments and 409 advisor changes (325 transfers, 43 promotions, 41 terminations). These are not defects. The SCD2 models test them, not DQ033.

## Earlier baseline

The first baseline (#52, code `586f759`) was a local 104-week backfill without the warm-up year: 1,535,275 raw activity rows, 1,472,505 kept, 55.5 minutes of wall time, about 37 s per weekly run and an 8.7 MB export. It found three bugs:

| Problem | Fix |
|---|---|
| DQ031 counted the partial weeks before the first extract in its baseline. | Fixed in #146. |
| Unbounded narrative history broke the 20 MB export budget at week 54. | Fixed in #148 (PR #150). |
| CI slowed to 29 minutes once the runner's generate stage used default sizes. | Fixed by small generate sizes in `tests/conftest.py`. |

Every run in it finished as WARN. Since #251 the booked-from relationship test warns only above 2% of at least 500 bookings, and template narration in backfilled history records SUCCESS. It also showed DQ031 warning on 16 holiday and small-dip weeks. Since #156 DQ031 divides each week by its business-calendar factor and warns only beyond 3σ **and** 5% of the adjusted mean. The rebuild above has no such warnings.

**On GitHub Actions** a backfill week then took 4–5 minutes, more than half of it in `restore_state`. #206 made restore download only files whose MD5 differs from R2's ETag, and added the `budget_minutes` input that splits a rebuild across runs, which is how the rebuild above ran.

## Reproducing at small scale

```bash
uv run pytest tests/integration/test_e2e.py -m slow
```

- **What it runs:** an 8-week cold backfill plus one weekly run, at the small sizes from `tests/conftest.py`.
- **What it asserts:**
  - generate, ingest and dbt_build succeed for every week.
  - DQ030, DQ032 and DQ033 pass every week.
  - The mart holds exactly the expected weeks.
