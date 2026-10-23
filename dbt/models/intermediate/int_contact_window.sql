-- Which weeks have a full 12-month contact window behind them (PLAN.md §7): the window
-- (week_end − 12 months, week_end] must start on or after the first completed activity.
-- Earlier weeks report the lead KPI as null, never as a partial window.
--
-- The report starts at the first week with a full window (#273): the generator loads a
-- warm-up year of activity before its first reported week, and those weeks feed the window
-- without being reported. A history shorter than a year (the fixtures, a short local run)
-- has no such week up to its last activity, so every week from the first activity is
-- reported. (dim_date runs past the history, and those later weeks always have a window.)
with first_activity as (
    select
        min(activity_date) as first_date,
        min(iso_week_id) as first_week,
        max(iso_week_id) as last_week
    from {{ ref('int_activity_enriched') }}
    where status = 'COMPLETED'
),

windows as (
    select
        weeks.iso_week_id,
        weeks.week_end,
        cast(weeks.week_end - interval 12 month as date) >= first_activity.first_date
            as is_window_complete,
        first_activity.first_week,
        first_activity.last_week
    from (
        select iso_week_id, max(week_end) as week_end
        from {{ ref('dim_date') }}
        group by iso_week_id
    ) as weeks
    cross join first_activity
)

select
    iso_week_id,
    week_end,
    is_window_complete,
    iso_week_id >= coalesce(
        min(iso_week_id) filter (where is_window_complete and iso_week_id <= last_week) over (),
        first_week
    ) as is_reported
from windows
