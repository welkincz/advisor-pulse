-- DQ011 sends invalid postal codes to FSA UNK, so the geography dimension always
-- has that member, with no province, district, region, or boundary.
select fsa_code
from {{ ref('dim_geography') }}
where fsa_code = 'UNK'
    and not (
        province_code is null
        and province_name is null
        and not is_rural
        and district_code is null
        and region_code is null
        and not has_boundary
    )
union all
select 'UNK' as fsa_code
where not exists (
    select 1 from {{ ref('dim_geography') }} where fsa_code = 'UNK'
)
