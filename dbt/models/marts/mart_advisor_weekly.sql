-- Advisor × week KPI parts (PLAN.md §6.8, §7). One row per active advisor and week:
-- employed at week start and not a branch manager. Activity by any branch counts toward
-- the advisor; activity with an unknown advisor (DQ012) is excluded here and credited to
-- its branch in mart_org_weekly.
with events as (
    select * from {{ ref('int_kpi_events') }}
),

roster as (
    select iso_week_id, advisor_id, branch_id
    from events
    where event_kind = 'advisor'
),

parts as (
    select
        iso_week_id,
        advisor_id,
        sum(activities_completed) as activities_completed,
        sum(calls_out) as calls_out,
        sum(calls_in) as calls_in,
        sum(appointments_booked) as appointments_booked,
        sum(appointments_held) as appointments_held,
        sum(no_shows) as no_shows,
        sum(conversions) as conversions,
        count(distinct contacted_client_id) as unique_clients_contacted,
        sum(portfolio_clients) as portfolio_clients,
        sum(portfolio_contacted_12m) as portfolio_contacted_12m,
        sum(meeting_minutes) as meeting_minutes,
        sum(meetings_held) as meetings_held
    from events
    where advisor_id is not null
    group by iso_week_id, advisor_id
)

select
    roster.iso_week_id,
    roster.advisor_id,
    roster.branch_id,
    org.district_code,
    org.region_code,
    cast(parts.activities_completed as bigint) as activities_completed,
    cast(parts.calls_out as bigint) as calls_out,
    cast(parts.calls_in as bigint) as calls_in,
    cast(parts.appointments_booked as bigint) as appointments_booked,
    cast(parts.appointments_held as bigint) as appointments_held,
    cast(parts.no_shows as bigint) as no_shows,
    cast(parts.conversions as bigint) as conversions,
    cast(parts.unique_clients_contacted as bigint) as unique_clients_contacted,
    round(parts.meeting_minutes / nullif(parts.meetings_held, 0), 2) as avg_meeting_duration_min,
    cast(parts.portfolio_clients as bigint) as portfolio_clients,
    cast(parts.portfolio_contacted_12m as bigint) as portfolio_contacted_12m,
    case when contact_window.is_window_complete then
        round(parts.portfolio_contacted_12m / nullif(parts.portfolio_clients, 0), 4)
    end as portfolio_contacted_rate_12m
from roster
inner join parts using (iso_week_id, advisor_id)
inner join {{ ref('int_contact_window') }} as contact_window using (iso_week_id)
inner join {{ ref('dim_org') }} as org on org.branch_id = roster.branch_id
