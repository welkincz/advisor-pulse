-- One row per client_id: the latest LAST_UPD_TS across the snapshot and deltas.
-- Postal codes normalize to `A1A 1A1`; anything that still fails the pattern gets fsa_code
-- 'UNK' (PLAN.md §6.6, DQ011). The pattern is patterns.POSTAL_CODE.
with renamed as (
    select
        "CLNT_ID" as client_id,
        cast("CLNT_SINCE_DT" as date) as client_since_date,
        cast("BRTH_YR" as integer) as birth_year,
        nullif(upper(trim("SEG_CD")), '') as segment_code,
        "PSTL_CD" as postal_raw,
        nullif(upper(trim("PROV_CD")), '') as province_code,
        "PRIM_ADVSR_ID" as primary_advisor_id,
        "PRIM_BRNCH_ID" as primary_branch_id,
        nullif(upper(trim("STAT_CD")), '') as status_code,
        cast("LAST_UPD_TS" as timestamp with time zone) as last_updated_ts,
        "_batch_id",
        "_loaded_at" as _loaded_at,
        "_source_file" as _source_file,
        "_source_row" as _source_row
    from {{ source('raw', 'teradata__clnt') }}
),

latest as (
    select *
    from renamed
    where client_id is not null
    qualify row_number() over (
        partition by client_id
        order by last_updated_ts desc, _loaded_at desc, _source_file desc, _source_row desc
    ) = 1
),

compacted as (
    select
        *,
        case
            when postal_raw is null then null
            else upper(replace(replace(trim(postal_raw), '-', ''), ' ', ''))
        end as postal_compact
    from latest
),

candidates as (
    select
        *,
        case
            when postal_compact is null then null
            else substr(postal_compact, 1, 3) || ' ' || substr(postal_compact, 4)
        end as postal_candidate
    from compacted
),

validated as (
    select
        *,
        coalesce(
            regexp_full_match(
                postal_candidate,
                '^[ABCEGHJ-NPRSTVXY][0-9][ABCEGHJ-NPRSTV-Z] [0-9][ABCEGHJ-NPRSTV-Z][0-9]$'
            ),
            false
        ) as postal_valid_flag
    from candidates
)

select
    client_id,
    client_since_date,
    birth_year,
    segment_code,
    case when postal_valid_flag then postal_candidate end as postal_code,
    case
        when postal_valid_flag then substr(postal_candidate, 1, 3) else 'UNK'
    end as fsa_code,
    postal_valid_flag,
    province_code,
    primary_advisor_id,
    primary_branch_id,
    status_code,
    last_updated_ts,
    _batch_id
from validated
