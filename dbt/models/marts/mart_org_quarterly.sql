-- Node × fiscal quarter KPIs at every level (PLAN.md §6.8, §7), exported as
-- org_quarterly.parquet. The fiscal year starts on 1 November (FY26 = 2025-11-01 to
-- 2026-10-31) and a week counts in the quarter that holds its Sunday (dim_date).
-- One GROUPING SETS pass over int_kpi_events, like mart_org_weekly:
--   flows (activities, calls, appointments) are summed over the quarter's weeks;
--   distinct clients are counted over the whole quarter, not added up week by week;
--   stocks (the lead KPI's portfolio clients and those contacted in 12 months) are taken at
--     each branch's own last reported week in the quarter, then summed up the hierarchy, so
--     a branch that misses the final week keeps its portfolios;
--   ratios are rebuilt from summed parts. Activities per advisor is activities over
--     advisor-weeks: the average weekly rate across the quarter.
with week_quarter as (
    select distinct
        dim_date.iso_week_id,
        dim_date.week_fiscal_quarter_id as fiscal_quarter_id
    from {{ ref('dim_date') }} as dim_date
),

quarters as (
    -- Every quarter's calendar span and how many ISO weeks report into it.
    select
        fiscal_quarter_id,
        any_value(fiscal_year) as fiscal_year,
        any_value(fiscal_quarter) as fiscal_quarter,
        any_value(fiscal_quarter_start) as quarter_start,
        any_value(fiscal_quarter_end) as quarter_end
    from {{ ref('dim_date') }}
    group by fiscal_quarter_id
),

weeks_per_quarter as (
    -- Sundays from the quarter's first Sunday to its last day: 12 to 14. Computed from the
    -- calendar, not from dim_date's rows, so a quarter cut by the date range still counts right.
    select
        fiscal_quarter_id,
        date_diff('day', quarter_start + cast((7 - isodow(quarter_start)) % 7 as integer), quarter_end) // 7 + 1
            as weeks_in_quarter
    from quarters
),

events as (
    select
        events.*,
        week_quarter.fiscal_quarter_id,
        org.district_code,
        org.region_code
    from {{ ref('int_kpi_events') }} as events
    inner join week_quarter on week_quarter.iso_week_id = events.iso_week_id
    inner join {{ ref('dim_org') }} as org on org.branch_id = events.branch_id
),

reported as (
    select
        fiscal_quarter_id,
        min(iso_week_id) as first_week,
        max(iso_week_id) as last_week,
        count(distinct iso_week_id) as weeks_reported
    from events
    group by fiscal_quarter_id
),

branch_last as (
    select fiscal_quarter_id, branch_id, max(iso_week_id) as last_week
    from events
    group by fiscal_quarter_id, branch_id
),

flows as (
    select
        fiscal_quarter_id,
        region_code,
        district_code,
        branch_id,
        grouping(region_code, district_code, branch_id) as grouping_id,
        sum(active_advisors) as advisor_weeks,
        sum(activities_completed) as activities_completed,
        sum(calls_out) as calls_out,
        sum(calls_in) as calls_in,
        sum(appointments_booked) as appointments_booked,
        sum(booked_from_call) as booked_from_call,
        sum(appointments_held) as appointments_held,
        sum(no_shows) as no_shows,
        sum(conversions) as conversions,
        count(distinct contacted_client_id) as unique_clients_contacted,
        sum(meeting_minutes) as meeting_minutes,
        sum(meetings_held) as meetings_held
    from events
    group by grouping sets (
        (fiscal_quarter_id),
        (fiscal_quarter_id, region_code),
        (fiscal_quarter_id, region_code, district_code),
        (fiscal_quarter_id, region_code, district_code, branch_id)
    )
),

stocks as (
    select
        events.fiscal_quarter_id,
        events.region_code,
        events.district_code,
        events.branch_id,
        grouping(events.region_code, events.district_code, events.branch_id) as grouping_id,
        sum(events.portfolio_clients) as portfolio_clients,
        sum(events.portfolio_contacted_12m) as portfolio_contacted_12m
    from events
    inner join branch_last
        on branch_last.fiscal_quarter_id = events.fiscal_quarter_id
        and branch_last.branch_id = events.branch_id
        and branch_last.last_week = events.iso_week_id
    group by grouping sets (
        (events.fiscal_quarter_id),
        (events.fiscal_quarter_id, events.region_code),
        (events.fiscal_quarter_id, events.region_code, events.district_code),
        (events.fiscal_quarter_id, events.region_code, events.district_code, events.branch_id)
    )
),

nodes as (
    select distinct 'REGION' as level, region_code as node_id, region_name as node_name, 'CA' as parent_id
    from {{ ref('dim_org') }}
    union all
    select distinct 'DISTRICT', district_code, district_name, region_code
    from {{ ref('dim_org') }}
    union all
    select 'BRANCH', branch_id, branch_name, district_code
    from {{ ref('dim_org') }}
),

leveled as (
    select
        flows.*,
        stocks.portfolio_clients,
        stocks.portfolio_contacted_12m,
        case flows.grouping_id when 7 then 'NATIONAL' when 3 then 'REGION' when 1 then 'DISTRICT' else 'BRANCH' end as level,
        case flows.grouping_id
            when 7 then 'CA' when 3 then flows.region_code when 1 then flows.district_code else flows.branch_id
        end as node_id
    from flows
    left join stocks
        on stocks.fiscal_quarter_id = flows.fiscal_quarter_id
        and stocks.grouping_id = flows.grouping_id
        and stocks.region_code is not distinct from flows.region_code
        and stocks.district_code is not distinct from flows.district_code
        and stocks.branch_id is not distinct from flows.branch_id
)

select
    leveled.fiscal_quarter_id,
    quarters.fiscal_year,
    quarters.fiscal_quarter,
    quarters.quarter_start,
    quarters.quarter_end,
    reported.first_week,
    reported.last_week,
    cast(reported.weeks_reported as integer) as weeks_reported,
    cast(weeks_per_quarter.weeks_in_quarter as integer) as weeks_in_quarter,
    reported.weeks_reported = weeks_per_quarter.weeks_in_quarter as is_complete,
    leveled.level,
    leveled.node_id,
    coalesce(nodes.node_name, 'Canada') as node_name,
    nodes.parent_id,
    cast(leveled.advisor_weeks as bigint) as advisor_weeks,
    cast(leveled.activities_completed as bigint) as activities_completed,
    cast(leveled.calls_out as bigint) as calls_out,
    cast(leveled.calls_in as bigint) as calls_in,
    cast(leveled.appointments_booked as bigint) as appointments_booked,
    cast(leveled.booked_from_call as bigint) as booked_from_call,
    cast(leveled.appointments_held as bigint) as appointments_held,
    cast(leveled.no_shows as bigint) as no_shows,
    cast(leveled.conversions as bigint) as conversions,
    cast(leveled.unique_clients_contacted as bigint) as unique_clients_contacted,
    round(leveled.meeting_minutes / nullif(leveled.meetings_held, 0), 2) as avg_meeting_duration_min,
    round(leveled.activities_completed / nullif(leveled.advisor_weeks, 0), 2) as activities_per_advisor,
    round(leveled.appointments_held / nullif(leveled.appointments_held + leveled.no_shows, 0), 4) as show_rate,
    round(leveled.conversions / nullif(leveled.appointments_held, 0), 4) as conversion_rate,
    round(leveled.booked_from_call / nullif(leveled.calls_out, 0), 4) as call_to_appt_rate,
    cast(coalesce(leveled.portfolio_clients, 0) as bigint) as portfolio_clients,
    cast(coalesce(leveled.portfolio_contacted_12m, 0) as bigint) as portfolio_contacted_12m,
    -- A stock: the rate at the quarter's last week, once it has a full year.
    case when contact_window.is_window_complete then
        round(leveled.portfolio_contacted_12m / nullif(leveled.portfolio_clients, 0), 4)
    end as portfolio_contacted_rate_12m
from leveled
inner join quarters on quarters.fiscal_quarter_id = leveled.fiscal_quarter_id
inner join reported on reported.fiscal_quarter_id = leveled.fiscal_quarter_id
inner join {{ ref('int_contact_window') }} as contact_window
    on contact_window.iso_week_id = reported.last_week
inner join weeks_per_quarter on weeks_per_quarter.fiscal_quarter_id = leveled.fiscal_quarter_id
left join nodes on nodes.level = leveled.level and nodes.node_id = leveled.node_id
