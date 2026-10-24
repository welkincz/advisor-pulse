-- Node × KPI × ISO week in long format (PLAN.md §6.8, §7), exported as weekly_report.parquet
-- for the dashboard and the AI narrative. Values come from mart_org_weekly, plus
-- the operational LATE_RATE and QUAR_RATE at national level from int_ingest_weekly.
--
--   prior_week_value  the same node and KPI in the previous ISO week
--   wow_pct           wow_delta ÷ prior_week_value; null when the prior value is 0 or null
--   trailing_13w_avg  mean of the non-null values in the 13 weeks ending this week
--   rank_in_parent    dense rank among nodes with the same parent, 1 = best; lower is
--                     better for NO_SHOW_RATE, LATE_RATE and QUAR_RATE. peer_count
--                     counts those nodes. Both are null at national level or for a null value
--   flag              ANOMALY when the value is more than 3 standard deviations from the
--                     13 weeks before it (with at least 8 of them non-null); for the
--                     smooth PRTF_CONTACT_12M, when the week's move (wow_delta) is more
--                     than 2 standard deviations from the moves of the 13 weeks before and
--                     at least 0.2 points; else UP or DOWN when WoW moved 1% or more,
--                     else FLAT. The thresholds come from the backtest against the
--                     generator's ground truth (ADR 0006, `make backtest`)
with org as (
    select * from {{ ref('mart_org_weekly') }}
),

kpis (kpi_code, lower_is_better) as (
    values
        ('PRTF_CONTACT_12M', false),
        ('ACT_PER_ADV', false),
        ('CALLS_OUT', false),
        ('APPT_BOOKED', false),
        ('CALL_TO_APPT', false),
        ('SHOW_RATE', false),
        ('APPT_CONV', false),
        ('CLIENTS_CONTACTED', false),
        ('AVG_MEET_MIN', false),
        ('NO_SHOW_RATE', true),
        ('LATE_RATE', true),
        ('QUAR_RATE', true)
),

org_values as (
    select
        org.iso_week_id,
        org.level,
        org.node_id,
        org.node_name,
        org.parent_id,
        kpis.kpi_code,
        cast(case kpis.kpi_code
            when 'PRTF_CONTACT_12M' then org.portfolio_contacted_rate_12m
            when 'ACT_PER_ADV' then org.activities_per_advisor
            when 'CALLS_OUT' then org.calls_out
            when 'APPT_BOOKED' then org.appointments_booked
            when 'CALL_TO_APPT' then org.call_to_appt_rate
            when 'SHOW_RATE' then org.show_rate
            when 'APPT_CONV' then org.conversion_rate
            when 'CLIENTS_CONTACTED' then org.unique_clients_contacted
            when 'AVG_MEET_MIN' then org.avg_meeting_duration_min
            when 'NO_SHOW_RATE' then round(1 - org.show_rate, 4)
        end as double) as value
    from org
    cross join kpis
    where kpis.kpi_code not in ('LATE_RATE', 'QUAR_RATE')
),

ops_values as (
    select
        org.iso_week_id,
        org.level,
        org.node_id,
        org.node_name,
        org.parent_id,
        kpis.kpi_code,
        case kpis.kpi_code
            when 'LATE_RATE' then round(batches.late_rows / nullif(batches.activity_loaded, 0), 4)
            when 'QUAR_RATE' then round(
                (batches.activity_quarantined + batches.client_quarantined)
                    / nullif(batches.activity_rows + batches.client_rows, 0),
                4
            )
        end as value
    from org
    inner join {{ ref('int_ingest_weekly') }} as batches using (iso_week_id)
    cross join kpis
    where org.level = 'NATIONAL' and kpis.kpi_code in ('LATE_RATE', 'QUAR_RATE')
),

weeks as (
    select iso_week_id, min(week_start) as week_start
    from {{ ref('dim_date') }}
    group by iso_week_id
),

report_values as (
    select all_values.*, weeks.week_start, kpis.lower_is_better
    from (select * from org_values union all select * from ops_values) as all_values
    inner join weeks using (iso_week_id)
    inner join kpis using (kpi_code)
),

windowed as (
    select
        current_week.*,
        prior_week.value as prior_week_value,
        avg(current_week.value) over trailing_13w as trailing_13w_avg,
        avg(current_week.value) over before_13w as baseline_avg,
        stddev_samp(current_week.value) over before_13w as baseline_sd,
        count(current_week.value) over before_13w as baseline_weeks,
        count(*) over siblings as peer_count,
        case
            when current_week.parent_id is not null and current_week.value is not null
                then dense_rank() over (
                    partition by
                        current_week.iso_week_id, current_week.level, current_week.parent_id,
                        current_week.kpi_code, current_week.value is null
                    order by
                        case when current_week.lower_is_better
                            then current_week.value else -current_week.value end
                )
        end as rank_in_parent
    from report_values as current_week
    left join report_values as prior_week
        on prior_week.level = current_week.level
        and prior_week.node_id = current_week.node_id
        and prior_week.kpi_code = current_week.kpi_code
        and prior_week.week_start = current_week.week_start - interval 7 day
    window
        trailing_13w as (
            partition by current_week.level, current_week.node_id, current_week.kpi_code
            order by current_week.week_start
            range between interval 84 day preceding and current row
        ),
        before_13w as (
            partition by current_week.level, current_week.node_id, current_week.kpi_code
            order by current_week.week_start
            range between interval 91 day preceding and interval 7 day preceding
        ),
        siblings as (
            partition by
                current_week.iso_week_id, current_week.level, current_week.parent_id,
                current_week.kpi_code
        )
),

compared as (
    select
        *,
        round(value - prior_week_value, 4) as wow_delta,
        round(round(value - prior_week_value, 4) / nullif(prior_week_value, 0), 4) as wow_pct
    from windowed
),

moves as (
    select
        *,
        avg(wow_delta) over before_13w as move_avg,
        stddev_samp(wow_delta) over before_13w as move_sd,
        count(wow_delta) over before_13w as move_weeks
    from compared
    window before_13w as (
        partition by level, node_id, kpi_code
        order by week_start
        range between interval 91 day preceding and interval 7 day preceding
    )
)

select
    iso_week_id,
    level,
    node_id,
    node_name,
    parent_id,
    kpi_code,
    value,
    prior_week_value,
    wow_delta,
    wow_pct,
    round(trailing_13w_avg, 4) as trailing_13w_avg,
    cast(rank_in_parent as bigint) as rank_in_parent,
    cast(case when rank_in_parent is not null then peer_count end as bigint) as peer_count,
    case
        when value is not null
            and baseline_weeks >= 8
            and baseline_sd > 0
            and abs(value - baseline_avg) / baseline_sd > 3
            and kpi_code <> 'PRTF_CONTACT_12M'
            then 'ANOMALY'
        -- A rolling 12-month rate moves smoothly, so a steady slide sits "2 sd" from the
        -- weeks before every week. Judge its weekly move against its usual weekly move
        -- instead, and only a move of 0.2 points or more.
        when kpi_code = 'PRTF_CONTACT_12M'
            and move_weeks >= 8
            and move_sd > 0
            and abs(wow_delta - move_avg) / move_sd > 2
            and abs(wow_delta) >= 0.002
            then 'ANOMALY'
        when wow_pct is null or abs(wow_pct) < 0.01 then 'FLAT'
        when wow_pct > 0 then 'UP'
        else 'DOWN'
    end as flag
from moves
