-- mart_geo_weekly has one row per ISO week, FSA and district (PLAN.md §6.8). An FSA can sit
-- under two districts, so consumers must sum across districts to get one value per FSA
-- (the web map does, #176); a duplicate within one district would double-count clients.
select iso_week_id, fsa_code, district_code, count(*) as rows_in_grain
from {{ ref('mart_geo_weekly') }}
group by iso_week_id, fsa_code, district_code
having count(*) > 1
