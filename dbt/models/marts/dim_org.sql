-- Branch dimension (PLAN.md §6.8). Grain is the org seed: one row per branch in
-- reference/org.yaml, including branches the fixture extract does not load.
-- close_date comes from stg_branch (the latest branch master row). A branch that
-- is not in the extract, or has a null close date, is open.
with branch as (
    select branch_id, close_date from {{ ref('stg_branch') }}
)

select
    md5(org.branch_id) as branch_sk,
    org.branch_id,
    org.branch_name,
    org.district_code,
    org.district_name,
    org.region_code,
    org.region_name,
    org.fsa_code,
    org.province_code,
    cast(org.open_date as date) as open_date,
    branch.close_date,
    branch.close_date is null as is_open
from {{ ref('org_branch') }} as org
left join branch on branch.branch_id = org.branch_id
