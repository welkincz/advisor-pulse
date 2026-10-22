-- mart_org_quarterly reproduces fixtures/exports/org_quarterly.parquet, which
-- src/pulse/fixtures.py computes independently in Python from the same truth (ratios allow
-- one unit in the last place for rounding). Returns every key or value that differs.
{{ config(enabled=target.name == 'ci') }}

with expected as (
    select * from read_parquet('fixtures/exports/org_quarterly.parquet')
)

select coalesce(e.fiscal_quarter_id, a.fiscal_quarter_id) as fiscal_quarter_id, coalesce(e.node_id, a.node_id) as node_id
from expected as e
full outer join {{ ref('mart_org_quarterly') }} as a using (fiscal_quarter_id, node_id)
where e.node_id is null or a.node_id is null
    or e.level is distinct from a.level
    or e.first_week is distinct from a.first_week
    or e.last_week is distinct from a.last_week
    or e.weeks_reported is distinct from a.weeks_reported
    or e.weeks_in_quarter is distinct from a.weeks_in_quarter
    or e.is_complete is distinct from a.is_complete
    or e.quarter_start is distinct from a.quarter_start
    or e.quarter_end is distinct from a.quarter_end
    or e.advisor_weeks is distinct from a.advisor_weeks
    or e.activities_completed is distinct from a.activities_completed
    or e.calls_out is distinct from a.calls_out
    or e.appointments_booked is distinct from a.appointments_booked
    or e.booked_from_call is distinct from a.booked_from_call
    or e.appointments_held is distinct from a.appointments_held
    or e.no_shows is distinct from a.no_shows
    or e.conversions is distinct from a.conversions
    or e.unique_clients_contacted is distinct from a.unique_clients_contacted
    or e.portfolio_clients is distinct from a.portfolio_clients
    or e.portfolio_contacted_12m is distinct from a.portfolio_contacted_12m
    or not ((e.portfolio_contacted_rate_12m is null and a.portfolio_contacted_rate_12m is null) or abs(e.portfolio_contacted_rate_12m - a.portfolio_contacted_rate_12m) <= 0.000101)
    or not ((e.activities_per_advisor is null and a.activities_per_advisor is null) or abs(e.activities_per_advisor - a.activities_per_advisor) <= 0.0101)
    or not ((e.show_rate is null and a.show_rate is null) or abs(e.show_rate - a.show_rate) <= 0.000101)
    or not ((e.call_to_appt_rate is null and a.call_to_appt_rate is null) or abs(e.call_to_appt_rate - a.call_to_appt_rate) <= 0.000101)
