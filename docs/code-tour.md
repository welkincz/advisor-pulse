# Read the code in 20 minutes

This tour is for a reviewer with little time, or for someone learning from the repo. It
follows one weekly run in data-flow order: contracts, synthetic sources, ingest, dbt
history, the lead KPI, data quality, and the AI narrative. Each stop is one file and the
20 to 40 lines worth reading, the question they answer, why it is built that way, and the
test that proves it.

All data is synthetic. The bank is Maplecrest Bank (fictional).

Every code link is pinned to commit
[`fbb4252`](https://github.com/welkincz/advisor-pulse/tree/fbb42525cdda2840bef32075ef2fa9e30203b826),
so the line ranges do not drift when `main` moves on.

| # | Stop | File | Lines |
|---|------|------|-------|
| 1 | Contracts and codegen | `src/pulse/contracts/base.py` | 91–130 |
| 2 | Defect manifest | `src/pulse/generate/dirt.py` | 543–579 |
| 3 | Ingest transaction | `src/pulse/ingest/snowflake.py` | 112–142 |
| 4 | SCD2 advisor history | `dbt/models/intermediate/int_advisor_history.sql` | 17–47 |
| 5 | Client book and portfolio holder | `dbt/models/intermediate/int_client_book_weekly.sql` | 77–99 |
| 6 | 12-month contacted KPI | `dbt/models/intermediate/int_client_contact_12m.sql` | 1–32 |
| 7 | DQ033 reconciliation | `src/pulse/quality/checks.py` | 80–118 |
| 8 | Narrative validator | `src/pulse/narrative/validate.py` | 120–164 |

## 1. Contracts and codegen

**Read:** [`src/pulse/contracts/base.py` L91–L130](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/src/pulse/contracts/base.py#L91-L130),
then [`codegen.py` L53–L62](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/src/pulse/contracts/codegen.py#L53-L62).

**Question:** How does one schema definition become a Parquet schema, a DuckDB table and a
JSON Schema file without the three drifting apart?

**Why:** Each table is a Pydantic model. `arrow_schema` and `duckdb_columns` derive the
physical types from the same fields, and `codegen --check` fails CI if the committed JSON
Schemas are stale. A column exists in one place, so nobody can add one silently.

**Test:** [`tests/contracts/test_physical.py`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/tests/contracts/test_physical.py#L58)
`test_arrow_schema_matches_columns` and `test_committed_schemas_are_fresh`.

## 2. The generator's defect manifest

**Read:** [`src/pulse/generate/dirt.py` L543–L579](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/src/pulse/generate/dirt.py#L543-L579).

**Question:** If the sources are synthetic, how do we know the pipeline catches the bad
rows?

**Why:** The generator writes clean files, then injects defects (duplicates, null IDs,
unknown advisors, late rows) and records each one by file, row and rule ID in a manifest.
The random state is seeded from `seed|week`, and an existing manifest is returned as is,
so a retry never injects twice. The manifest is the ground truth that stop 7 checks.

**Test:** [`tests/generate/test_dirt.py`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/tests/generate/test_dirt.py#L142)
`test_same_seed_and_week_reproduce_sources_and_manifest` and
`test_completed_week_retry_does_not_inject_again`.

## 3. The ingest transaction: rows, watermark and file manifest

**Read:** [`src/pulse/ingest/snowflake.py` L112–L142](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/src/pulse/ingest/snowflake.py#L112-L142).
The transaction opens at [L74](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/src/pulse/ingest/snowflake.py#L74),
and the already-loaded check is at [L161–L166](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/src/pulse/ingest/snowflake.py#L161-L166).

**Question:** What happens if a load crashes halfway, or the same file arrives twice?

**Why:** Raw rows, quarantined rows, the watermark and the file manifest are written in
one DuckDB transaction per file, so a failure leaves none of them behind. A file is
skipped when its path and SHA-256 are already in the manifest, so a rerun is a no-op. The
watermark only moves forward ([`meta.py` L92–L108](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/src/pulse/ingest/meta.py#L92-L108)).

**Test:** [`tests/ingest/test_snowflake.py`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/tests/ingest/test_snowflake.py#L172)
`test_insert_failure_rolls_back_raw_watermark_manifest_and_quarantine` and
`test_identical_rerun_reports_duplicate_and_does_not_write`.

## 4. SCD2 advisor history from events

**Read:** [`dbt/models/intermediate/int_advisor_history.sql` L17–L47](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/dbt/models/intermediate/int_advisor_history.sql#L17-L47).

**Question:** Which branch and role did an advisor have on a given date?

**Why:** Ranges are built from HR assignment events with `lead()`, not from dbt
snapshots. The same events always give the same ranges, so a full backfill is
deterministic ([ADR 0001](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/docs/adr/0001-scd2-from-events.md)).
Two events on one day keep the later one, and a TERM event closes the last range.

**Test:** dbt singular tests
[`dbt/tests/scd2_no_overlap.sql`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/dbt/tests/scd2_no_overlap.sql)
and [`dbt/tests/scd2_no_gaps.sql`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/dbt/tests/scd2_no_gaps.sql)
(DQ020), run by `make dbt-build-ci`.

## 5. The client book and the portfolio holder at week end

**Read:** [`dbt/models/intermediate/int_client_book_weekly.sql` L77–L99](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/dbt/models/intermediate/int_client_book_weekly.sql#L77-L99),
then [`int_portfolio_history.sql` L9–L36](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/dbt/models/intermediate/int_portfolio_history.sql#L9-L36).

**Question:** Whose book is a client in at the end of a given week?

**Why:** A client belongs to a portfolio, and a portfolio has exactly one holder at a
time. The book joins the client version in force at Sunday 23:59 Toronto time to the
portfolio's holder on that date. When a portfolio is handed over, its clients move with
it and the transit branch stays the same. Client versions come from every loaded row, so
a mid-period change is not lost.

**Test:** [`dbt/tests/assert_client_book_portfolio_handover.sql`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/dbt/tests/assert_client_book_portfolio_handover.sql)
(one handover in the fixtures, checked before and after), and
[`tests/dbt/test_portfolio_history_dq024.py`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/tests/dbt/test_portfolio_history_dq024.py#L19)
`test_dq024_returns_one_row_per_problem` for the holder ranges.

## 6. The 12-month contacted KPI and its completeness window

**Read:** [`dbt/models/intermediate/int_client_contact_12m.sql` L1–L32](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/dbt/models/intermediate/int_client_contact_12m.sql#L1-L32),
then [`int_contact_window.sql` L1–L20](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/dbt/models/intermediate/int_contact_window.sql#L1-L20)
and the rollup in [`mart_portfolio_weekly.sql` L22–L37](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/dbt/models/marts/mart_portfolio_weekly.sql#L22-L37).

**Question:** What share of a portfolio's active clients had a completed contact in the
last 12 months, and when is that number trustworthy?

**Why:** An ASOF join finds each client's last contact on or before week end in one
pass, instead of scanning a year of activity for every week. A contact by any advisor
counts. The mart reports the rate only when a full 12 months of history sits behind the
week; earlier weeks show null, never a partial window that would look like a drop.

**Test:** dbt unit tests
[`int_client_contact_12m_counts_any_advisor_inside_twelve_months`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/dbt/models/intermediate/int_client_contact_12m.yml#L44)
(11 months counts, 12 months and a day does not) and
[`int_contact_window_needs_twelve_months_behind_the_week`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/dbt/models/intermediate/int_contact_window.yml#L21).

## 7. DQ033: reconciliation against ground truth

**Read:** [`src/pulse/quality/checks.py` L80–L118](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/src/pulse/quality/checks.py#L80-L118),
then the comparison in [`policy.py` L205–L223](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/src/pulse/quality/policy.py#L205-L223).

**Question:** Did ingest quarantine exactly the rows the generator broke, no more and no
fewer?

**Why:** Both sides become sets of `(file, row, rule_id)`. Missing means a defect got
through; unexpected means a good row was rejected. On a rerun it compares against the
latest batch of each file, so a no-op run does not look like a miss. DQ033 fails in CI
and warns in the weekly run.

**Test:** [`tests/quality/test_checks.py`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/tests/quality/test_checks.py#L132)
`test_defect_reconciliation_uses_prior_loaded_batch_on_rerun`, and end to end
[`tests/integration/test_e2e.py`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/tests/integration/test_e2e.py#L34)
`test_backfill_then_weekly_run_passes_every_check`.

## 8. The narrative validator

**Read:** [`src/pulse/narrative/validate.py` L120–L164](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/src/pulse/narrative/validate.py#L120-L164).

**Question:** How do we stop the AI summary from inventing a number or getting a
direction wrong?

**Why:** Every number in the text must match a fact the sentence cites, within the
rounding the text shows. A number that matches only an uncited fact is flagged as
uncited; one that matches nothing is fabricated. A direction word such as "rose" must
agree with the fact's sign. Banned phrases cover advice, speculation about causes, and
wording that oversells how fresh the data is. A failed draft gets one retry with
feedback, then the template text is used.

**Test:** [`tests/narrative/test_validate.py`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/tests/narrative/test_validate.py#L63)
`test_fabricated_number_is_caught`, `test_uncited_claim_is_caught`,
`test_wrong_sign_on_a_delta_is_caught` and `test_two_failures_fall_back_to_the_template`.

## If you have five more minutes

- **Run log and failure handling.**
  [`src/pulse/runner/run.py` L164–L198](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/src/pulse/runner/run.py#L164-L198)
  retries only transient errors and writes one `run_log` row per attempt with the error
  message. Tests: [`tests/runner/test_runner.py`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/tests/runner/test_runner.py#L156)
  `test_retryable_error_twice_then_success_logs_attempts_1_to_3` and
  `test_retries_exhausted_fails_and_skips_downstream`.
- **The web data layer.**
  [`web/src/data/wasm.ts` L9–L30](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/web/src/data/wasm.ts#L9-L30)
  loads DuckDB-WASM in a worker on first use and exposes each exported Parquet file as a
  view, so the site runs SQL in the browser with no backend. Test:
  [`web/src/data/hooks.test.tsx`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/web/src/data/hooks.test.tsx#L74)
  "a failed fetch shows a calm notice with the last run time, and retry recovers".
- **Idempotency end to end.**
  [`tests/integration/test_idempotency.py`](https://github.com/welkincz/advisor-pulse/blob/fbb42525cdda2840bef32075ef2fa9e30203b826/tests/integration/test_idempotency.py#L97)
  `test_crash_between_loaders_recovers_to_clean_state` crashes ingest after the activity
  load, reruns it, and checks that the warehouse ends in the same state as a clean run.
