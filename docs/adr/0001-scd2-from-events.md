# ADR 0001 — SCD2 advisor history from assignment events, not dbt snapshots

- Status: Accepted
- Date: 2026-10-16
- Issue: #24

## Context

Activity is credited to the advisor's branch **as of the activity date** (PLAN.md §7), so
the warehouse needs advisor history as SCD2 ranges. dbt offers two ways to get them:

1. **`dbt snapshot`**: compare the current `ADVSR_ASGN` state with the last snapshot on
   every run, and stamp changes with the run's timestamp (`dbt_valid_from`).
2. **Build ranges from events**: the source already keeps every assignment as an event
   (`ASGN_ID`, `EFF_DT`, `RSN_CD` = HIRE, TRANSFER, PROMOTION, TERM), so the ranges are
   `lead(effective_date)` over each advisor's events.

The pipeline must be able to rebuild everything from scratch: a cold start when R2 has
no state (#45), and `pulse backfill --rebuild`. Both must give the same warehouse as the
weekly runs that came before.

## Decision

Build `int_advisor_history` from events. Each non-TERM event opens a range from its
`effective_date` to the advisor's next event (exclusive), or `9999-12-31` while open. A
TERM event opens nothing, so it closes the last range on the termination date. Two events
on one day keep the later `ASGN_ID`. `dim_advisor` adds names and hierarchy, plus the
Unknown member (`advisor_sk = 'UNKNOWN'`).

`advisor_sk` is `md5(advisor_id || '|' || valid_from)`: it depends only on the natural
key, so it is the same after every rebuild. `tests/scd2_advisor_sk_stable.sql` pins two
values so a formula change is caught.

## Why not snapshots

- **Not deterministic on rebuild.** Snapshot validity comes from *when dbt ran*, not when
  the change took effect. A backfill run today would stamp every past change with today's
  date, and a rebuilt warehouse would differ from the original.
- **Not rebuildable.** A snapshot table is state that only accumulates. Lose it and the
  history is gone, while the events in the source are still there.
- **Wrong dates.** A transfer effective Monday but loaded Thursday would start on
  Thursday, and three days of activity would be credited to the old branch.

## Consequences

- SCD2 is plain SQL over staging: rebuilt in full every run, small (one row per event),
  and tested for overlaps, gaps and current-row counts (DQ020, `tests/scd2_*.sql`, error
  severity).
- It relies on the source keeping every event. That holds for `ADVSR_ASGN`. If a source
  only exposed current state, a snapshot would be the right tool. PLAN.md §3 keeps
  snapshots documented as that path.
- Back-dated events (an `EFF_DT` earlier than events already loaded) are handled for free:
  the next rebuild re-derives every range.
