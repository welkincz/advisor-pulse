-- One row per KPI event from the main project's int_kpi_events (PLAN.md §7 building
-- blocks), plus the week's Monday as the time dimension and the 12-month window guard.
-- No KPI logic lives here: the semantic layer aggregates these additive parts.
with weeks as (
    select iso_week_id, min(week_start) as week_start
    from {{ source('pulse_marts', 'dim_date') }}
    group by iso_week_id
)

select
    row_number() over (
        -- int_kpi_events has no event id: order by every column, so rows that tie are
        -- identical and the ids are the same on every build.
        order by events.iso_week_id, events.branch_id, events.event_kind,
            events.advisor_id, events.contacted_client_id, events.activities_completed,
            events.calls_out, events.calls_in, events.appointments_booked,
            events.booked_from_call, events.appointments_held, events.no_shows,
            events.conversions, events.meeting_minutes, events.meetings_held,
            events.active_advisors, events.portfolio_clients, events.portfolio_contacted_12m
    ) as kpi_event_id,
    events.*,
    weeks.week_start,
    contact_window.is_window_complete
from {{ source('pulse_intermediate', 'int_kpi_events') }} as events
inner join weeks using (iso_week_id)
inner join {{ source('pulse_intermediate', 'int_contact_window') }} as contact_window
    using (iso_week_id)
