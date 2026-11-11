-- Branch → district → region hierarchy, copied from the main project's dim_org.
select branch_id, branch_name, district_code, district_name, region_code, region_name
from {{ source('pulse_marts', 'dim_org') }}
