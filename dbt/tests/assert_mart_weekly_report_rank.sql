-- rank_in_parent is dense and 1 = best: within one parent, week and KPI, ranks run 1..n
-- over the n distinct values, and rank 1 holds the highest value, or the lowest for
-- NO_SHOW_RATE, LATE_RATE and QUAR_RATE. Returns every group that breaks this.
select iso_week_id, level, parent_id, kpi_code
from {{ ref('mart_weekly_report') }}
where rank_in_parent is not null
group by iso_week_id, level, parent_id, kpi_code
having max(rank_in_parent) <> count(distinct value)
    or count(distinct rank_in_parent) <> count(distinct value)
    or count(distinct value) <> count(distinct value || '|' || rank_in_parent)
    or min(case when rank_in_parent = 1 then value end) <> case
        when kpi_code in ('NO_SHOW_RATE', 'LATE_RATE', 'QUAR_RATE') then min(value)
        else max(value)
    end
