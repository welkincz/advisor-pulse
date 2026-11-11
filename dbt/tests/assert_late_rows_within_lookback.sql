-- Rows in the newest activity extract that take effect before the weekly models' lookback
-- (#304, dbt/macros/weekly_incremental.sql). The runner's stamp still rebuilds their weeks,
-- so this warns, not fails: it says the generator's "at most 3 weeks late, booked at most a
-- week ahead" no longer holds, and a weekly run rebuilt more history than usual. A plain
-- `dbt build` without the runner's stamps would leave those weeks stale.
-- One row per activity: its effective day (activity, booking or schedule, the earliest)
-- and the first day the lookback covers (the extract's week, less one week and the lookback).
{{ config(severity='warn') }}

with latest as (
    select max({{ iso_week_start(toronto_date('extracted_at')) }}) as extract_week_start
    from {{ ref('stg_activity') }}
),

newest as (
    select
        activity.activity_id,
        activity.extracted_at,
        least(
            activity.activity_date,
            coalesce({{ toronto_date('activity.created_ts') }}, activity.activity_date),
            coalesce({{ toronto_date('activity.scheduled_ts') }}, activity.activity_date)
        ) as effective_date,
        latest.extract_week_start - {{ 7 * (var('weekly_lookback_weeks', 4) | int + 1) }}
            as lookback_start
    from {{ ref('stg_activity') }} as activity
    cross join latest
    where {{ iso_week_start(toronto_date('activity.extracted_at')) }} = latest.extract_week_start
)

select activity_id, extracted_at, effective_date, lookback_start
from newest
where effective_date < lookback_start
