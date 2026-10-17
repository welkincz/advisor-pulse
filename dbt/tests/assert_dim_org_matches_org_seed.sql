-- dim_org has exactly the org.yaml branches (via the org_branch seed), with the
-- same hierarchy. Close date is operational and is not part of the seed.
select seed.branch_id
from {{ ref('org_branch') }} as seed
left join {{ ref('dim_org') }} as dim on dim.branch_id = seed.branch_id
where
    dim.branch_id is null
    or dim.branch_name is distinct from seed.branch_name
    or dim.district_code is distinct from seed.district_code
    or dim.district_name is distinct from seed.district_name
    or dim.region_code is distinct from seed.region_code
    or dim.region_name is distinct from seed.region_name
    or dim.fsa_code is distinct from seed.fsa_code
    or dim.province_code is distinct from seed.province_code
    or dim.open_date is distinct from cast(seed.open_date as date)
    or dim.district_code is null
    or dim.district_name is null
    or dim.region_code is null
    or dim.region_name is null
union all
select dim.branch_id
from {{ ref('dim_org') }} as dim
left join {{ ref('org_branch') }} as seed on seed.branch_id = dim.branch_id
where seed.branch_id is null
