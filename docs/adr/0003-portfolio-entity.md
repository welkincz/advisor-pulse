# ADR 0003 — Portfolio as its own entity; the book owner is its holder at week end

- Status: Accepted
- Date: 2026-10-21
- Issues: #219, #220, #223

## Context

Until #219 a client's book owner was one column on the client: `CLNT.PRIM_ADVSR_ID`. The
lead KPI asks a different question: of the clients in the portfolios an advisor holds,
how many heard from the bank in the last twelve months. That needs three things the old
column could not give:

1. **A group that outlives its advisor.** When an advisor leaves, Maplecrest Bank
   (fictional) hands the whole group of clients to a colleague at the same branch. With
   only `PRIM_ADVSR_ID`, a handover is thousands of separate client updates that may
   arrive over several days.
2. **A home branch for the group.** A portfolio belongs to a branch (its *transit*). An
   advisor who transfers leaves the portfolio behind, so the branch's KPI must not move
   with the person.
3. **History.** Who held the portfolio on a given date, built the same way on every
   rebuild.

## Decision

Model the portfolio as its own source entity, with the holder kept as assignment events:

- `PRTF` (`PRTF_ID`, `BRNCH_ID` = transit, `OPEN_DT`, `CLOSE_DT`) and `PRTF_ASGN`
  (`PASGN_ID`, `PRTF_ID`, `ADVSR_ID`, `EFF_DT`, `RSN_CD` = OPEN, HANDOVER, TRANSFER,
  REBALANCE). A client names its portfolio in `CLNT.PRTF_ID`.
- `int_portfolio_history` builds SCD2 holder ranges from those events, the same way
  `int_advisor_history` does (ADR 0001): each event opens a range up to the next one.
- **The book owner is the holder of the client's portfolio on `week_end`**, read in
  `int_client_book_weekly`. The portfolio's KPI is credited to that holder and to the
  transit branch, never to the holder's own branch.
- **Fallback:** a null `PRTF_ID` (rows from before portfolios) or one the master lacks
  falls back to `PRIM_ADVSR_ID`. Unknown IDs are counted by **DQ014** and kept out of the
  lead KPI, which only counts known portfolios. PLAN.md §8 sets two thresholds on the share
  of the active book: WARN above 0.5% and FAIL above 2%. The WARN step is enforced by
  `dq014_unknown_portfolio_rate` (severity warn). The FAIL step is enforced by
  `dq014_unknown_portfolio_rate_fail` (severity error), which a separate PR adds.
- **DQ024** (error) checks the holder ranges: no range before the portfolio opened, no
  overlap or gap, and every holder an employed, non-manager advisor when the range starts.
  **DQ025** (warn) flags a portfolio whose holder works at another branch than its transit
  at week end: usually a reassignment that has not arrived yet.

## Alternatives considered

- **Keep `PRIM_ADVSR_ID` and derive "portfolio" as advisor × branch.** No new source, but
  a handover would reset the group, a transfer would carry the clients to the new branch,
  and two portfolios held by one advisor would merge.
- **Credit the holder on each activity's date.** That answers "who made the call"; the KPI
  asks "whose portfolio is it now". Week end matches how the book is already read (the
  client version in force at Sunday 23:59 Toronto).
- **Drop or quarantine clients with an unknown `PRTF_ID`.** They are real, active clients.
  Dropping them would shrink the book silently; the advisor fallback keeps them in the
  book and DQ014 makes the gap visible.

## Consequences

- A handover is one `PRTF_ASGN` event, and every client moves on the same day.
- The book and `dim_client.primary_advisor_id` agree, because the dimension now reads the
  latest book week.
- The fallback depends on `PRIM_ADVSR_ID`, which is deprecated. It goes away with the
  contract step (#226, ADR 0004); after that an unknown portfolio maps to the Unknown member
  only.
- DQ025 warns in the fixtures by design: two in-window movers keep their portfolios at the
  old transit.

## Code and tests

- Contracts: [`src/pulse/contracts/sources.py`](../../src/pulse/contracts/sources.py)
- Staging: [`stg_portfolio.sql`](../../dbt/models/staging/stg_portfolio.sql),
  [`stg_portfolio_assignment.sql`](../../dbt/models/staging/stg_portfolio_assignment.sql)
- History: [`int_portfolio_history.sql`](../../dbt/models/intermediate/int_portfolio_history.sql)
- Book owner and fallback: [`int_client_book_weekly.sql`](../../dbt/models/intermediate/int_client_book_weekly.sql)
- DQ014: [`mart_dq_weekly.sql`](../../dbt/models/marts/mart_dq_weekly.sql),
  [`dq014_unknown_portfolio_rate.sql`](../../dbt/tests/dq014_unknown_portfolio_rate.sql),
  injection tested by `test_unknown_portfolio_is_injected_and_recorded` in
  [`tests/generate/test_dirt.py`](../../tests/generate/test_dirt.py)
- DQ024: [`assert_portfolio_history_dq024.sql`](../../dbt/tests/assert_portfolio_history_dq024.sql),
  failure cases in [`tests/dbt/test_portfolio_history_dq024.py`](../../tests/dbt/test_portfolio_history_dq024.py)
- DQ025: `dq025_portfolio_holder_at_another_branch` in
  [`mart_portfolio_weekly.yml`](../../dbt/models/marts/mart_portfolio_weekly.yml)
- Handover: [`assert_client_book_portfolio_handover.sql`](../../dbt/tests/assert_client_book_portfolio_handover.sql),
  [`tests/generate/test_portfolios.py`](../../tests/generate/test_portfolios.py)
