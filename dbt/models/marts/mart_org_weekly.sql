-- Node × week KPIs at every level (PLAN.md §6.8, §7), from one GROUPING SETS pass over
-- int_kpi_events: national, region, district and branch. Counts are summed, distinct
-- clients are counted at each level, and every ratio is computed after the roll-up from
-- its summed numerator and denominator, never by averaging child ratios.
with events as (
    select
        events.*,
        org.district_code,
        org.region_code
    from {{ ref('int_kpi_events') }} as events
    inner join {{ ref('dim_org') }} as org on org.branch_id = events.branch_id
),

rolled as (
    select
        iso_week_id,
        region_code,
        district_code,
        branch_id,
        grouping(region_code, district_code, branch_id) as grouping_id,
        sum(active_advisors) as active_advisors,
        sum(activities_completed) as activities_completed,
        sum(calls_out) as calls_out,
        sum(calls_in) as calls_in,
        sum(appointments_booked) as appointments_booked,
        sum(booked_from_call) as booked_from_call,
        sum(appointments_held) as appointments_held,
        sum(no_shows) as no_shows,
        sum(conversions) as conversions,
        count(distinct contacted_client_id) as unique_clients_contacted,
        sum(portfolio_clients) as portfolio_clients,
        sum(portfolio_contacted_12m) as portfolio_contacted_12m,
        sum(meeting_minutes) as meeting_minutes,
        sum(meetings_held) as meetings_held
    from events
    group by grouping sets (
        (iso_week_id),
        (iso_week_id, region_code),
        (iso_week_id, region_code, district_code),
        (iso_week_id, region_code, district_code, branch_id)
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
        rolled.*,
        case grouping_id when 7 then 'NATIONAL' when 3 then 'REGION' when 1 then 'DISTRICT' else 'BRANCH' end as level,
        case grouping_id when 7 then 'CA' when 3 then region_code when 1 then district_code else branch_id end as node_id
    from rolled
)

select
    leveled.iso_week_id,
    leveled.level,
    leveled.node_id,
    coalesce(nodes.node_name, 'Canada') as node_name,
    nodes.parent_id,
    cast(leveled.active_advisors as bigint) as active_advisors,
    cast(leveled.activities_completed as bigint) as activities_completed,
    cast(leveled.calls_out as bigint) as calls_out,
    cast(leveled.calls_in as bigint) as calls_in,
    cast(leveled.appointments_booked as bigint) as appointments_booked,
    cast(leveled.appointments_held as bigint) as appointments_held,
    cast(leveled.no_shows as bigint) as no_shows,
    cast(leveled.conversions as bigint) as conversions,
    cast(leveled.unique_clients_contacted as bigint) as unique_clients_contacted,
    round(leveled.meeting_minutes / nullif(leveled.meetings_held, 0), 2) as avg_meeting_duration_min,
    round(leveled.activities_completed / nullif(leveled.active_advisors, 0), 2) as activities_per_advisor,
    round(leveled.appointments_held / nullif(leveled.appointments_held + leveled.no_shows, 0), 4) as show_rate,
    round(leveled.conversions / nullif(leveled.appointments_held, 0), 4) as conversion_rate,
    round(leveled.booked_from_call / nullif(leveled.calls_out, 0), 4) as call_to_appt_rate,
    cast(leveled.portfolio_clients as bigint) as portfolio_clients,
    cast(leveled.portfolio_contacted_12m as bigint) as portfolio_contacted_12m,
    case when contact_window.is_window_complete then
        round(leveled.portfolio_contacted_12m / nullif(leveled.portfolio_clients, 0), 4)
    end as portfolio_contacted_rate_12m
from leveled
left join nodes on nodes.level = leveled.level and nodes.node_id = leveled.node_id
inner join {{ ref('int_contact_window') }} as contact_window using (iso_week_id)
