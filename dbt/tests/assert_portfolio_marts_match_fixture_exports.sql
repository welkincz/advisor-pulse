-- The lead KPI's marts reproduce fixtures/exports (computed independently in Python by
-- src/pulse/fixtures.py): mart_portfolio_weekly row for row, and the portfolio columns of
-- mart_geo_weekly and mart_org_quarterly. Rates allow one unit in the last place.
{{ config(enabled=target.name == 'ci') }}


select 'mart_portfolio_weekly' as model, coalesce(e.iso_week_id, a.iso_week_id) as iso_week_id,
    coalesce(e.portfolio_id, a.portfolio_id) as node_id
from read_parquet('fixtures/exports/portfolio_weekly.parquet') as e
full outer join {{ ref('mart_portfolio_weekly') }} as a using (iso_week_id, portfolio_id)
where e.portfolio_id is null or a.portfolio_id is null
    or e.advisor_id is distinct from a.advisor_id
    or e.branch_id is distinct from a.branch_id
    or e.holder_branch_id is distinct from a.holder_branch_id
    or e.clients is distinct from a.clients
    or e.contacted_12m is distinct from a.contacted_12m
    or not ((e.contacted_rate_12m is null and a.contacted_rate_12m is null)
        or abs(e.contacted_rate_12m - a.contacted_rate_12m) <= 0.000101)

union all

select 'mart_geo_weekly', e.iso_week_id, e.fsa_code
from read_parquet('fixtures/exports/geo_weekly.parquet') as e
full outer join {{ ref('mart_geo_weekly') }} as a using (iso_week_id, fsa_code, district_code)
where e.fsa_code is null or a.fsa_code is null
    or e.portfolio_clients is distinct from a.portfolio_clients
    or e.portfolio_contacted_12m is distinct from a.portfolio_contacted_12m
    or e.portfolio_contacted_rate_12m is distinct from a.portfolio_contacted_rate_12m

union all

select 'mart_org_quarterly', e.fiscal_quarter_id, e.node_id
from read_parquet('fixtures/exports/org_quarterly.parquet') as e
full outer join {{ ref('mart_org_quarterly') }} as a using (fiscal_quarter_id, node_id)
where e.node_id is null or a.node_id is null
    or e.portfolio_clients is distinct from a.portfolio_clients
    or e.portfolio_contacted_12m is distinct from a.portfolio_contacted_12m
    or e.portfolio_contacted_rate_12m is distinct from a.portfolio_contacted_rate_12m
