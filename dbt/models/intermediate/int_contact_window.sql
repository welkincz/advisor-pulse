-- Which weeks have a full 12-month contact window behind them (PLAN.md §7): the window
-- (week_end − 12 months, week_end] must start on or after the first completed activity.
-- Earlier weeks report the lead KPI as null, never as a partial window.
with first_activity as (
    select min(activity_date) as first_date
    from {{ ref('int_activity_enriched') }}
    where status = 'COMPLETED'
)

select
    weeks.iso_week_id,
    weeks.week_end,
    cast(weeks.week_end - interval 12 month as date) >= first_activity.first_date
        as is_window_complete
from (
    select iso_week_id, max(week_end) as week_end
    from {{ ref('dim_date') }}
    group by iso_week_id
) as weeks
cross join first_activity
