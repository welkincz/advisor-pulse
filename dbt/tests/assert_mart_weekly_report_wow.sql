-- Week over week: null in a node's first week, otherwise the previous ISO week's value of
-- the same node and KPI, with wow_delta and wow_pct from it. Returns every row that is off.
with report as (
    select report.*, dim_date.week_start
    from {{ ref('mart_weekly_report') }} as report
    inner join (
        select iso_week_id, min(week_start) as week_start from {{ ref('dim_date') }} group by 1
    ) as dim_date using (iso_week_id)
)

select current_week.iso_week_id, current_week.node_id, current_week.kpi_code
from report as current_week
left join report as prior_week
    on prior_week.level = current_week.level
    and prior_week.node_id = current_week.node_id
    and prior_week.kpi_code = current_week.kpi_code
    and prior_week.week_start = current_week.week_start - 7
where current_week.prior_week_value is distinct from prior_week.value
    or current_week.wow_delta is distinct from round(current_week.value - prior_week.value, 4)
    or (prior_week.value <> 0 and abs(current_week.wow_pct - current_week.wow_delta / prior_week.value) > 0.0001)
    or (prior_week.value = 0 and current_week.wow_pct is not null)
    or (
        current_week.iso_week_id = (select min(iso_week_id) from report)
        and (current_week.prior_week_value is not null or current_week.wow_pct is not null)
    )
