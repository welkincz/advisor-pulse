-- Grain: advisor × week and node × week. Returns one row per duplicate key.
select 'mart_advisor_weekly' as model, iso_week_id, advisor_id as node_id, count(*) as row_count
from {{ ref('mart_advisor_weekly') }}
group by iso_week_id, advisor_id
having count(*) > 1

union all

select 'mart_org_weekly', iso_week_id, node_id, count(*)
from {{ ref('mart_org_weekly') }}
group by iso_week_id, node_id
having count(*) > 1
