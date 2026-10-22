-- The active book, read through the portfolio holder, is the lead KPI's denominator. On
-- the ci target the active clients in known portfolios, grouped by the holder at week end,
-- have to match portfolio_clients in fixtures/exports/advisor_weekly.parquet (PLAN.md §7).
{{ config(enabled=target.name == 'ci') }}

with expected as (
    select iso_week_id, advisor_id, portfolio_clients
    from read_parquet('fixtures/exports/advisor_weekly.parquet')
    where portfolio_clients > 0
),

actual as (
    select
        iso_week_id,
        primary_advisor_id as advisor_id,
        count(*) as portfolio_clients
    from {{ ref('int_client_book_weekly') }}
    where is_active
        and not is_unknown_portfolio
        and iso_week_id in (select iso_week_id from expected)
    group by iso_week_id, primary_advisor_id
)

select
    coalesce(expected.iso_week_id, actual.iso_week_id) as iso_week_id,
    coalesce(expected.advisor_id, actual.advisor_id) as advisor_id,
    expected.portfolio_clients as expected_portfolio_clients,
    actual.portfolio_clients as actual_portfolio_clients
from expected
full outer join actual using (iso_week_id, advisor_id)
where coalesce(expected.portfolio_clients, 0) <> coalesce(actual.portfolio_clients, 0)

union all

select null, null, null, null
where (select count(*) from expected) = 0
