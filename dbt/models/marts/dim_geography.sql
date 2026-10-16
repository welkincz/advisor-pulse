-- FSA dimension (PLAN.md §6.8). Every branch FSA, every current client FSA, and
-- UNK (DQ011, postal codes that do not normalize). Client rules match stg_client:
-- latest row per client, postal `A1A 1A1`, otherwise fsa_code UNK. is_rural is
-- the Canada Post rule (second character 0). has_boundary is the shipped StatCan layer.
with branch_fsa as (
    select fsa_code, district_code, region_code
    from {{ ref('org_branch') }}
    qualify row_number() over (partition by fsa_code order by branch_id) = 1
),

client_renamed as (
    select
        "CLNT_ID" as client_id,
        "PSTL_CD" as postal_raw,
        cast("LAST_UPD_TS" as timestamp with time zone) as last_updated_ts,
        "_loaded_at" as _loaded_at,
        "_source_file" as _source_file,
        "_source_row" as _source_row
    from {{ source('raw', 'teradata__clnt') }}
),

client_latest as (
    select *
    from client_renamed
    where client_id is not null
    qualify row_number() over (
        partition by client_id
        order by last_updated_ts desc, _loaded_at desc, _source_file desc, _source_row desc
    ) = 1
),

client_compacted as (
    select
        case
            when postal_raw is null then null
            else upper(replace(replace(trim(postal_raw), '-', ''), ' ', ''))
        end as postal_compact
    from client_latest
),

client_fsa as (
    select distinct
        case
            when coalesce(
                regexp_full_match(
                    substr(postal_compact, 1, 3) || ' ' || substr(postal_compact, 4),
                    '^[ABCEGHJ-NPRSTVXY][0-9][ABCEGHJ-NPRSTV-Z] [0-9][ABCEGHJ-NPRSTV-Z][0-9]$'
                ),
                false
            ) then substr(postal_compact, 1, 3)
            else 'UNK'
        end as fsa_code
    from client_compacted
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
