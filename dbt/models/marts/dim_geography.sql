-- FSA dimension (PLAN.md §6.8). Every branch FSA, every current client FSA from
-- stg_client (which already maps postal codes that do not normalize to UNK, DQ011),
-- and UNK itself. is_rural is the Canada Post rule (second character 0). has_boundary
-- is the shipped StatCan layer.
with branch_fsa as (
    select fsa_code, district_code, region_code
    from {{ ref('org_branch') }}
    qualify row_number() over (partition by fsa_code order by branch_id) = 1
),

client_fsa as (
    select distinct fsa_code from {{ ref('stg_client') }}
),

fsa as (
    select fsa_code from branch_fsa
    union
    select fsa_code from client_fsa
    union
    select 'UNK' as fsa_code
)

select
    fsa.fsa_code,
    province.province_code,
    province.province_name,
    substr(fsa.fsa_code, 2, 1) = '0' as is_rural,
    branch_fsa.district_code,
    branch_fsa.region_code,
    boundary.fsa_code is not null as has_boundary
from fsa
left join branch_fsa on branch_fsa.fsa_code = fsa.fsa_code
left join {{ ref('fsa_province') }} as province
    on province.fsa_first_letter = substr(fsa.fsa_code, 1, 1)
    and fsa.fsa_code <> 'UNK'
left join {{ ref('fsa_boundary') }} as boundary on boundary.fsa_code = fsa.fsa_code
