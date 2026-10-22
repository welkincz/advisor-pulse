# ADR 0004 — Expand, then contract: adding PRTF_ID before dropping PRIM_ADVSR_ID

- Status: Accepted — expand done (#220 to #225); contract step done in #226
- Date: 2026-10-21
- Issues: #219, #220, #226

## Context

ADR 0003 moves book ownership from `CLNT.PRIM_ADVSR_ID` to the holder of `CLNT.PRTF_ID`.
That change touches every layer: contracts, generator, ingest, dbt, exports, narrative and
web. Three constraints shaped how to ship it:

1. **Every PR stays green and under ~400 lines** (AGENTS.md §2). One PR across seven
   layers would be several thousand lines and impossible to review.
2. **The weekly run must keep working in between.** Production restores its warehouse
   from R2 every Monday. That warehouse has a `CLNT` table without `PRTF_ID`, and years of
   history without portfolios.
3. **The new path has to be proven on real history** before the old one goes. A new KPI
   that only exists in 4-week fixtures has never had a full 12-month window.

## Decision

Migrate in two phases.

- **Expand (#220 to #225).** Add the new sources (`PRTF`, `PRTF_ASGN`), make
  `CLNT.PRTF_ID` *optional* and append it last, and add the new KPI and export columns
  next to the old ones. Then the generator, ingest, dbt, export and web each switch over
  in their own PR. Both paths run side by side: the book uses the portfolio's holder when
  `PRTF_ID` resolves and `PRIM_ADVSR_ID` when it does not, and `COVERAGE_13W` is still
  computed.
- **Production rebuild.** History from before portfolios has no `PRTF_ID`, so one full
  rebuild (`pulse backfill --rebuild`, split into time-budgeted jobs by #206) regenerates
  it. The rebuilt report is the check that the new path works on a full year.
- **Contract (#226), only after that rebuild.** Drop `CLNT.PRIM_ADVSR_ID`, `COVERAGE_13W`,
  `book_size`, `clients_covered_13w` and `coverage_rate_13w`, and make `PRTF_ID` required.

To survive the Monday restore, `init_warehouse` adds any **nullable** contract column an
existing table lacks (`ALTER TABLE … ADD COLUMN`). That is the whole guarantee: missing
nullable columns are added, and a new required column is never added, so the insert fails
loudly. `add_column_sql` compares column names only, not types. A stale type can survive
without an error, because DuckDB may cast values to the old type on insert (for example
VARCHAR to an integer). So a type change needs a planned rebuild, which expand/contract
calls for anyway.

Status note (#226): the contract step removed the five columns, made `PRTF_ID` required
and took out the fallback. A dropped column is not removed from a restored warehouse, and
stored narratives still cite `COVERAGE_13W`, so it rolls out with one more full rebuild
(`pulse backfill --rebuild`), as this ADR expects for anything that is not additive.

## Alternatives considered

- **One big-bang PR.** Simplest history, but unreviewable, and the first Monday after
  merge would run new code against a warehouse with the old schema.
- **Keep both columns for good.** No risky drop, but two owners for one client is a trap:
  a later model could read the wrong one, and the deprecated KPI would keep costing
  compute and screen space.
- **Hand-written migration scripts.** Gives full control, but adds a second source of
  truth next to the contracts. Contracts already define the columns, so deriving the
  additive `ALTER`s from them keeps one source.
- **Auto-ALTER every missing column, required ones too.** A required column added to a
  table with rows would need a default, which would invent data. Failing is better.

## Consequences

- Ten PRs instead of one, each green on its own; the dbt, export and web steps merged as a
  stack (#237 to #242).
- During the expand phase the code carries both paths. `int_client_book_weekly` says in a
  comment that the fallback goes with #226, and the contract marks `PRIM_ADVSR_ID` deprecated.
- The contract step is a breaking change by design: it needs the owner's OK
  (AGENTS.md §2.7) and comes after the rebuild, not before.
- Schema evolution in place is limited to additive, nullable columns. Anything else,
  including a type change, needs a planned rebuild, which the pipeline already supports
  because every model is rebuilt from source.

## Code and tests

- Additive evolution: `add_column_sql` and `init_warehouse` in
  [`src/pulse/warehouse.py`](../../src/pulse/warehouse.py); tested by
  `test_restored_warehouse_gains_new_optional_columns` and
  `test_new_required_columns_are_not_added_silently` in
  [`tests/ingest/test_meta.py`](../../tests/ingest/test_meta.py)
- Optional `PRTF_ID` and deprecated `PRIM_ADVSR_ID`:
  [`src/pulse/contracts/sources.py`](../../src/pulse/contracts/sources.py)
- Both paths in the book: [`int_client_book_weekly.sql`](../../dbt/models/intermediate/int_client_book_weekly.sql)
- Old source files without portfolio tables still load: `test_old_edw_without_portfolio_tables_skips_them` in
  [`tests/ingest/test_teradata_hr.py`](../../tests/ingest/test_teradata_hr.py)
- Rebuild in time-budgeted jobs: [`src/pulse/runner/backfill.py`](../../src/pulse/runner/backfill.py),
  [`.github/workflows/backfill.yml`](../../.github/workflows/backfill.yml)
