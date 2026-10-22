-- The weekly marts reproduce fixtures/exports exactly (PLAN.md §7). The fixture values are
-- computed independently in Python by src/pulse/fixtures.py; ratios allow one unit in the last place for rounding
-- (half up here, half even in Python). Returns every key or value that differs.
{{ config(enabled=target.name == 'ci') }}

with expected_advisor as (
    select * from read_parquet('fixtures/exports/advisor_weekly.parquet')
),

expected_org as (
    select * from read_parquet('fixtures/exports/org_weekly.parquet')
)

select 'mart_advisor_weekly' as model, coalesce(e.iso_week_id, a.iso_week_id) as iso_week_id,
    coalesce(e.advisor_id, a.advisor_id) as node_id
from expected_advisor as e
full outer join {{ ref('mart_advisor_weekly') }} as a using (iso_week_id, advisor_id)
where e.advisor_id is null or a.advisor_id is null
    or e.branch_id is distinct from a.branch_id
    or e.activities_completed is distinct from a.activities_completed
    or e.calls_out is distinct from a.calls_out
    or e.calls_in is distinct from a.calls_in
    or e.appointments_booked is distinct from a.appointments_booked
    or e.appointments_held is distinct from a.appointments_held
    or e.no_shows is distinct from a.no_shows
    or e.conversions is distinct from a.conversions
    or e.unique_clients_contacted is distinct from a.unique_clients_contacted
    or e.portfolio_clients is distinct from a.portfolio_clients
    or e.portfolio_contacted_12m is distinct from a.portfolio_contacted_12m
    or not ((e.portfolio_contacted_rate_12m is null and a.portfolio_contacted_rate_12m is null) or abs(e.portfolio_contacted_rate_12m - a.portfolio_contacted_rate_12m) <= 0.000101)
    or not ((e.avg_meeting_duration_min is null and a.avg_meeting_duration_min is null) or abs(e.avg_meeting_duration_min - a.avg_meeting_duration_min) <= 0.0101)

union all

select 'mart_org_weekly', coalesce(e.iso_week_id, a.iso_week_id), coalesce(e.node_id, a.node_id)
from expected_org as e
full outer join {{ ref('mart_org_weekly') }} as a using (iso_week_id, node_id)
where e.node_id is null or a.node_id is null
    or e.level is distinct from a.level
    or e.node_name is distinct from a.node_name
    or e.parent_id is distinct from a.parent_id
    or e.activities_completed is distinct from a.activities_completed
    or e.calls_out is distinct from a.calls_out
    or e.calls_in is distinct from a.calls_in
    or e.appointments_booked is distinct from a.appointments_booked
    or e.appointments_held is distinct from a.appointments_held
    or e.no_shows is distinct from a.no_shows
    or e.conversions is distinct from a.conversions
    or e.unique_clients_contacted is distinct from a.unique_clients_contacted
    or e.portfolio_clients is distinct from a.portfolio_clients
    or e.portfolio_contacted_12m is distinct from a.portfolio_contacted_12m
    or not ((e.portfolio_contacted_rate_12m is null and a.portfolio_contacted_rate_12m is null) or abs(e.portfolio_contacted_rate_12m - a.portfolio_contacted_rate_12m) <= 0.000101)
    or e.active_advisors is distinct from a.active_advisors
    or not ((e.show_rate is null and a.show_rate is null) or abs(e.show_rate - a.show_rate) <= 0.000101)
    or not ((e.conversion_rate is null and a.conversion_rate is null) or abs(e.conversion_rate - a.conversion_rate) <= 0.000101)
    or not ((e.call_to_appt_rate is null and a.call_to_appt_rate is null) or abs(e.call_to_appt_rate - a.call_to_appt_rate) <= 0.000101)
    or not ((e.avg_meeting_duration_min is null and a.avg_meeting_duration_min is null) or abs(e.avg_meeting_duration_min - a.avg_meeting_duration_min) <= 0.0101)
    or not ((e.activities_per_advisor is null and a.activities_per_advisor is null) or abs(e.activities_per_advisor - a.activities_per_advisor) <= 0.0101)

union all

select 'fixtures missing', null, null
where (select count(*) from expected_advisor) = 0 or (select count(*) from expected_org) = 0
