-- mart_weekly_report, mart_geo_weekly and mart_dq_weekly reproduce fixtures/exports, which
-- src/pulse/fixtures.py computes independently in Python. Tolerances: one unit in the last
-- place, since mart_org_weekly rounds half up and Python half even, and a WoW percentage
-- inherits that from a 2-decimal value. The fixtures flag ANOMALY on a stricter rule meant
-- for their 3 prior weeks; those rows are only checked to be UP or DOWN here, and the mart
-- rule has its own unit test. Returns every key or value that differs.
{{ config(enabled=target.name == 'ci') }}

{% set close_to = "not coalesce(abs(e.{0} - a.{0}) <= {1}, e.{0} is null and a.{0} is null)" %}

select 'mart_weekly_report' as model, coalesce(e.iso_week_id, a.iso_week_id) as iso_week_id,
    coalesce(e.node_id, a.node_id) || '|' || coalesce(e.kpi_code, a.kpi_code) as key
from read_parquet('fixtures/exports/weekly_report.parquet') as e
full outer join {{ ref('mart_weekly_report') }} as a using (iso_week_id, node_id, kpi_code)
where e.kpi_code is null or a.kpi_code is null
    or e.level is distinct from a.level
    or e.node_name is distinct from a.node_name
    or e.parent_id is distinct from a.parent_id
    or {{ close_to.format('value', 0.0101) }}
    or {{ close_to.format('prior_week_value', 0.0101) }}
    or {{ close_to.format('wow_delta', 0.0201) }}
    or {{ close_to.format('wow_pct', '0.000101 + 0.0201 / abs(e.prior_week_value)') }}
    or {{ close_to.format('trailing_13w_avg', 0.0101) }}
    or e.rank_in_parent is distinct from a.rank_in_parent
    or e.peer_count is distinct from a.peer_count
    or (e.flag <> 'ANOMALY' and e.flag <> a.flag)
    or (e.flag = 'ANOMALY' and a.flag not in ('UP', 'DOWN'))

union all

select 'mart_geo_weekly', coalesce(e.iso_week_id, a.iso_week_id),
    coalesce(e.fsa_code, a.fsa_code) || '|' || coalesce(e.district_code, a.district_code)
from read_parquet('fixtures/exports/geo_weekly.parquet') as e
full outer join {{ ref('mart_geo_weekly') }} as a using (iso_week_id, fsa_code, district_code)
where e.fsa_code is null or a.fsa_code is null
    or e.active_clients is distinct from a.active_clients
    or e.portfolio_clients is distinct from a.portfolio_clients
    or e.portfolio_contacted_12m is distinct from a.portfolio_contacted_12m
    or e.activities_completed is distinct from a.activities_completed
    or {{ close_to.format('portfolio_contacted_rate_12m', 0.000101) }}

union all

select 'mart_dq_weekly', coalesce(e.iso_week_id, a.iso_week_id), coalesce(e.rule_id, a.rule_id)
from read_parquet('fixtures/exports/dq_weekly.parquet') as e
full outer join {{ ref('mart_dq_weekly') }} as a using (iso_week_id, rule_id)
where e.rule_id is null or a.rule_id is null
    or e.rule_name is distinct from a.rule_name
    or e.action is distinct from a.action
    or e.rows_affected is distinct from a.rows_affected
    or e.rows_in_batch is distinct from a.rows_in_batch
    or {{ close_to.format('rate', 0.000101) }}
