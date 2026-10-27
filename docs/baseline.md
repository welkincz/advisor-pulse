# Baseline: the 107-week rebuild

These numbers come from the last full rebuild of the real pipeline at the generator's default scale on synthetic Maplecrest Bank (fictional) data, with the one-year warm-up added in #273. They are the reference for later performance work and for the case study. Every figure names its source.

## Sources

| Source | What it is |
|---|---|
| Run [40262960502](https://github.com/welkincz/advisor-pulse/actions/runs/40262960502) | `backfill.yml` with `rebuild=true`, 2024-W41 to 2026-W43, code `e71a946`. One run: it rebuilt, built the site and deployed it. |
| Artifact `backfill-40262960502` | `run_log.json` with stage timings and row counts, and `runner_profile.json` (AMD EPYC 7763, 4 vCPU). |
| Run [40364746899](https://github.com/welkincz/advisor-pulse/actions/runs/40364746899) | The scheduled weekly run that followed, for 2026-W43, same code (AMD EPYC 9V74, 4 vCPU). Its artifact holds the built site measured under "Export sizes". |
| Local reproduction | The same code and seed on an Apple M4 Max with no R2 credentials and no model backend (commands below). It gives the warehouse row counts, which the Actions runs do not upload. Its `mart_dq_weekly` and `mart_org_weekly` match the deployed exports row for row, so the counts are the deployed run's counts. |

```bash
export PULSE_DATA_DIR=run/data PULSE_EXPORT_DIR=run/export   # the export dir must not exist yet
uv run pulse backfill --from 2024-W41 --to 2026-W43 --rebuild
```

The national 12-month contacted rate rises from 82.9% in 2024-W41 to 86.5% in 2026-W43, by at most 0.09 points a week (`org_weekly.parquet` on the deployed site).

## Outcome

| | Result |
|---|---|
| Weeks | 107, 2024-W41 to 2026-W43 (`weeks_available` in `manifest.json`) |
| Weekly ingest | 107 of 107 weeks SUCCESS, 0 retries |
| `dbt_build` | Once, after the last week: "529 dbt nodes passed" |
| `checks` | Evaluated for every week: WARN in 8 (2024-W41 to W48), PASS in 99 |
| `narrate` | Templates for the 106 historical weeks. In 2026-W43 the model wrote all 27 narratives and every one passed validation. |

- **The 8 check warnings** are DQ031 with a pending baseline: those weeks have fewer than 8 reported weeks before them. DQ030, DQ032 and DQ033 passed in all 107 weeks, in the run and in the local reproduction.
- **DQ033 defect reconciliation** found nothing missing and nothing unexpected in any week.

## Row counts per layer (after 2026-W43)

From the local reproduction's `warehouse.duckdb`.

| Layer | Table | Rows |
|---|---|---:|
| raw | `snowflake__activity` | 2,280,313 |
| raw | `teradata__clnt` | 288,752 |
| raw | `teradata__advsr` / `teradata__advsr_asgn` | 1,371 / 1,577 |
| raw | `teradata__prtf` / `teradata__prtf_asgn` | 1,320 / 2,049 |
| raw | `teradata__brnch` | 122 |
| quarantine | `rejected_rows` | 5,967 |
| staging | `stg_activity` | 2,216,806 |
| staging | `stg_client` | 153,359 |
| staging | `stg_advisor` / `stg_advisor_assignment` | 962 / 1,577 |
| intermediate | `int_activity_enriched` | 2,216,806 |
| intermediate | `int_kpi_events` | 18,132,512 |
| intermediate | `int_client_book_weekly` | 25,396,985 |
| intermediate | `int_client_contact_12m` | 22,346,189 |
| intermediate | `int_advisor_history` | 1,515 |
| marts | `fct_activity` | 2,216,806 |
| marts | `dim_client` / `dim_advisor` / `dim_org` | 153,359 / 1,516 / 122 |
| marts | `mart_weekly_report` | 160,714 |
| marts | `mart_portfolio_weekly` | 122,221 |
| marts | `mart_advisor_weekly` | 83,277 |
| marts | `mart_org_weekly` | 16,050 |
| marts | `mart_geo_weekly` | 14,873 |
| marts | `mart_org_quarterly` | 1,350 |
| marts | `mart_dq_weekly` | 963 |

### How activity rows become staging

| Step | Rows | Change |
|---|---:|---:|
| Activity rows read (159 extract files, `load_manifest.row_count`) | 2,286,280 | |
| Quarantined by DQ001–DQ003, never loaded to raw | | 5,967 |
| Loaded to `raw.snowflake__activity` | 2,280,313 | |
| Collapsed by DQ010 dedupe (exact duplicates and resent updates) | | 63,507 |
| Staging activity | 2,216,806 | |

- **Warm-up year:** 727,378 of the rows read come from the 52 clean warm-up extracts that the first week loads (#273), so the 12-month contacted rate has a full window from 2024-W41. They are loaded, never reported.
- **Reported weeks:** the other 1,558,902 rows belong to the 107 reported weeks (`rows_in_batch` for DQ001 in `mart_dq_weekly`), and 1,489,428 of them are kept.

## Duration

### The rebuild on GitHub Actions

Run 40262960502, 03:12 to 04:31 UTC: **1 h 18 min** in one run, of which 76.3 min is the backfill step and the rest is the recap video, site build and deploy. The stages, from its `run_log.json`:

| Stage | Seconds | What it covers |
|---|---:|---|
| generate + ingest, week by week | 3,680 | 107 weeks in order, each logged as its own run |
| dbt_build | 127 | Once, over all history |
| checks | 103 | DQ030–DQ033 for each of the 107 weeks |
| narrate | 559 | Templates for history; 27 model narratives for 2026-W43 |
| export | 6 | 34 files |
| persist_state | 101 | Warehouse, sources and narratives to R2 |

- **Per week**, from the `Backfill n/107` timestamps: the first week took 159 s because it generates and loads the warm-up year; later weeks took 18 s at the start, growing to 34 s at the end. Generation is most of it (median 27 s) and ingest about 5 s.
- **Checkpoints:** this run still persisted to R2 every 8 weeks, about 16 minutes in all (335 s for the first, about 50 s for each later one), although it finished far inside its 320-minute budget. Since #350 a run checkpoints only when its forecast says it may hit the budget; a clean stop still persists before continuing.
- **Locally**, the same 107 weeks take 18.7 minutes on an Apple M4 Max, with no R2 and no model.

### How the rebuild got faster

| Rebuild | Code | Time |
|---|---|---:|
| Per-week replay, 106 weeks | `ef841e1` | 6 h 22 min, in two runs |
| Build, check and publish once (#275); bulk raw inserts (#347) | `e71a946` | 1 h 18 min, in one run |

- **#275** generates and ingests each week in order, then builds dbt, runs every week's checks, narrates, exports and persists once, instead of replaying the whole pipeline for every week.
- **#347** inserts raw rows as one Arrow batch. Row-by-row `executemany` probed for pandas on every row, at about 1.3 ms a row.
- **What is left** is mostly the generator, about 80% of a rebuild (#349), and the checkpoints that #350 removes.

### Generator speed-up (#349, 2026-10-26)

The 1 h 18 min rebuild above predates this change. The comparison below is a separate, automatic branch-push measurement: [run 40269471066](https://github.com/welkincz/advisor-pulse/actions/runs/40269471066), base `e71a946`, implementation `a79a691`. Both versions run in the same job: Ubuntu 26.04 image `20261023.163.3`, AMD EPYC 9V74, 4 available CPUs, Python 3.12.15. Earlier jobs used a different CPU; their timings are not mixed into this comparison.

Default seed `20261013`, 900 advisors, 150,000 clients; generate 2026-W42 from identical 2026-W41 state. Each trial starts a fresh Python process. The initial 52-week history load is setup and excluded; building the world and writing the new week are timed. Three trials per version alternate order. **All 72 resulting files match byte for byte**, including SQLite and defect manifests, in every timed and profiled trial.

| Unprofiled weekly seconds | Before | After |
|---|---:|---:|
| Median | 16.986 | 3.758 |
| Maximum | 17.170 | 3.831 |

Separate `cProfile` trials; cumulative rows overlap and include instrumentation overhead:

| Function | Before (s) | After (s) |
|---|---:|---:|
| `generate_weeks` | 33.520 | 7.182 |
| `build_world` | 29.755 | 4.475 |
| `generate_clients` | 28.693 | 4.088 |
| `generate_portfolios` | 0.763 | 0.105 |
| `generate_week` | 3.762 | 2.706 |

The old client loop called `district` 83,701,968 times. Ordered district pools remove those calls. Portfolio handovers replace 667,926 `on_roster` calls with 39 indexed event dates. Client replay keeps the original quarter scheduling bounds and random draws through the requested Sunday, retains versions only for the required range, and reuses immutable dates and segment weights. Cyclic GC scans are deferred within the batch call, with the caller's setting restored on success or error; reference counting remains active. Seeds, sizes, story calibration and contracts are unchanged.

**Full local rebuild:** `2024-W41..2026-W42 --rebuild`, default seed/scale, separate empty data/export directories, Apple M4 Max, Python 3.12.11, dbt 4 threads, DuckDB 14 threads, templates only, no remote state. Main `e71a946`: **1169.516 s (19.49 min)**; `a79a691`: **532.343 s (8.87 min)**. These are single local trials, not a new Actions total. All **1009 source/defect files** match byte for byte; the final pipeline completed all 106 weeks, and all 14 marts have identical row counts and content hashes. Its WARN result is expected: early DQ031 baselines are pending and the latest narrative uses a template. The latest Actions rebuild remains the 1 h 18 min figure above; a post-merge remote rebuild is the owner's decision.

The measurement job uploads JSON hashes/timings, raw `.pstats` and `runner-profile.json`. The temporary helper is preserved in the [measurement commit](https://github.com/welkincz/advisor-pulse/blob/a79a691/scripts/profile_generation.py), outside the final production diff. In a worktree at that commit, reproduce the weekly comparison with `uv run python scripts/profile_generation.py --base e71a946 --out data/generator-profile.json`. `tests/generate/test_incremental.py` is unchanged; full-history digests from pre-optimization main, retained-history equivalence, roster work bounds and GC restoration have regression coverage.

### One weekly run

Run 40364746899 re-ran 2026-W43 on the rebuilt state, so generate and ingest found nothing new and the narratives came from the cache:

| Stage | Seconds |
|---|---:|
| restore_state | 480 |
| generate / ingest | 1 (already present) |
| dbt_build | 99 |
| checks | 0.8 |
| narrate | 0.7 (27 from cache) |
| export | 5 |
| persist_state | 32 |
| **Whole run** | **620** |

- **A new week** adds about 27 s of generation, 5 s of ingest (2026-W43 read 172,443 rows, loaded 15,263 and quarantined 57) and, with the model, about 9 minutes of narration: 27 Claude calls, one per region and district.
- **Restore is the largest cost.** Each run starts on a fresh runner and downloads the warehouse plus about 1,200 source and narrative files from R2. It took 3.5 to 4 minutes for the weekly runs of 2026-W42 and 8 minutes now. #304's target of a weekly run under a minute starts there.

**Parallel restore (#354), local measurement (2026-10-26).** Restore now uses 16
workers for all source and narrative files, then a 16-worker managed ranged download
for the warehouse (16 MiB chunks). The previous code serialized files, although
boto3 already downloaded the warehouse in parallel using its SDK defaults. MD5
skips, warehouse markers, stream/request retries and atomic replacement remain;
the full source/narrative history is restored before persist can run.

Reproduce with `uv run python tests/state/benchmark_restore.py`. On an Apple M4 Max,
macOS 26.6.2, Python 3.12.11, boto3 1.43.113 and moto 5.2.4, the in-process moto store
held 910 sources (64 KiB each), 280 narratives (4 KiB each) and a 1 GiB warehouse.
Fresh-directory restores took **10.834 s before / 6.163 s after (1.76×)**; SHA-256
matched the seeded bytes for every one of the 1,191 files in both destinations.
Seeding and hash verification are outside the timed restore. These are synthetic
payloads with no network latency; the local ratio does not predict R2 performance.
With `--latency-ms 10` (an artificial 10 ms delay per S3 request), the same check
took 40.544 s before / 6.365 s after (6.37×). This is a latency model, not an R2
measurement; all 1,191 file hashes matched again.

- [ ] After the first weekly run with #354, compare its `restore_state` duration
  and `runner_profile.json` with run 40364746899; verify the **under 90 s** target
  and add the Actions run link and measured stage times here. The 480 s baseline
  above remains the last verified Actions result until then.

**Comparing timings.** Every weekly and backfill run writes `runner_profile.json` into its artifact, and every CI python and dbt job prints the same fields: CPU model and count, `nproc`, runner image, Python, dbt-core, dbt-duckdb and DuckDB versions, threads and the commit (#336). Compare stage times only when the profiles match. #335 found a 49% dbt slowdown that came from the runner, not the code; to check a code change, rerun both commits on one machine.

## Export sizes (site after 2026-W43)

From the built site in the artifact of run 40364746899; the bytes match `manifest.json`.

| File | Bytes |
|---|---:|
| `weekly_report.parquet` | 3,255,165 |
| `org_weekly.parquet` | 375,866 |
| `portfolio_weekly.parquet` | 259,393 |
| `advisor_weekly.parquet` | 241,414 |
| `org_quarterly.parquet` | 69,919 |
| `run_log.json` | 39,631 |
| `geo_weekly.parquet` | 20,210 |
| `manifest.json` | 9,999 |
| `dq_weekly.parquet` | 6,768 |
| `pipeline_graph.json` | 6,069 |
| `narratives/*.json` (26 files, 2026-W18 to W43) | 7,007,944 |
| **Total** | **11,292,378** (56% of the 20 MB budget) |

- **`weekly_report.parquet`** grew by 0.47 MB when #310 stopped rounding `wow_pct`, so the change shown always equals value ÷ prior − 1.
- **Narratives:** the site keeps the latest 26 weeks, about 270 KB each (#148). Older narratives stay in state only: 44 MB for 107 weeks in the local reproduction.
- **Local state:** `warehouse.duckdb` is 1.2 GB and the generated sources are 158 MB.

## Defect catch rate

Over the 107 reported weeks the generator injected and recorded these defects (`defects.json` in the local reproduction). The warm-up extracts are clean. DQ033 compares the manifest with what the pipeline did, week by week, and found no missed and no unexpected rows in any week.

| Defect | Expected action | Rule | Injected |
|---|---|---|---:|
| Null activity id | Quarantine | DQ001 | 2,989 |
| Invalid enum | Quarantine | DQ002 | 1,490 |
| Duration out of range | Quarantine | DQ003 | 1,488 |
| Exact duplicate | Dedupe | DQ010 | 20,742 |
| Resent update | Dedupe | DQ010 | 42,765 |
| Dirty postal code | Normalize | DQ011 | 23,092 |
| Unknown advisor | Map to unknown | DQ012 | 4,473 |
| Unknown portfolio | Map to unknown | DQ014 | 400 |
| Late-arriving activity | Keep, flagged | — | 59,398 |

- **Quarantine:** 2,989 + 1,490 + 1,488 = 5,967, exactly the rows in `quarantine.rejected_rows`.
- **Dedupe:** 20,742 + 42,765 = 63,507, exactly the rows DQ010 collapsed.
- **Change events:** the generator also recorded 31,415 client reassignments and 409 advisor changes (325 transfers, 43 promotions, 41 terminations). These are not defects. The SCD2 models test them, not DQ033.

## Earlier baseline

The first baseline (#52, code `586f759`) was a local 104-week backfill without the warm-up year: 1,535,275 raw activity rows, 1,472,505 kept, 55.5 minutes of wall time, about 37 s per weekly run and an 8.7 MB export. It found three bugs:

| Problem | Fix |
|---|---|
| DQ031 counted the partial weeks before the first extract in its baseline. | Fixed in #146. |
| Unbounded narrative history broke the 20 MB export budget at week 54. | Fixed in #148 (PR #150). |
| CI slowed to 29 minutes once the runner's generate stage used default sizes. | Fixed by small generate sizes in `tests/conftest.py`. |

Every run in it finished as WARN. Since #251 the booked-from relationship test warns only above 2% of at least 500 bookings, and template narration in backfilled history records SUCCESS. It also showed DQ031 warning on 16 holiday and small-dip weeks. Since #156 DQ031 divides each week by its business-calendar factor and warns only beyond 3σ **and** 5% of the adjusted mean. The rebuild above has no such warnings.

## Reproducing at small scale

```bash
uv run pytest tests/integration/test_e2e.py -m slow
```

- **What it runs:** an 8-week cold backfill plus one weekly run, at the small sizes from `tests/conftest.py`.
- **What it asserts:**
  - generate, ingest and dbt_build succeed for every week.
  - DQ030, DQ032 and DQ033 pass every week.
  - The mart holds exactly the expected weeks.
