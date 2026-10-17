-- Grain of the three #28 marts. Returns one row per duplicated key.
select 'mart_weekly_report' as model, iso_week_id, node_id || '|' || kpi_code as key, count(*) as row_count
from {{ ref('mart_weekly_report') }}
group by iso_week_id, level, node_id, kpi_code
having count(*) > 1

union all

select 'mart_geo_weekly', iso_week_id, fsa_code || '|' || district_code, count(*)
from {{ ref('mart_geo_weekly') }}
group by iso_week_id, fsa_code, district_code
having count(*) > 1

union all

select 'mart_dq_weekly', iso_week_id, rule_id, count(*)
from {{ ref('mart_dq_weekly') }}
group by iso_week_id, rule_id
having count(*) > 1
