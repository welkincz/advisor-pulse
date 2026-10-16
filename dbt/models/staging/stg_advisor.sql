-- One row per advisor_id, the latest LAST_UPD_TS (PLAN.md §6.6).
with renamed as (
    select
        "ADVSR_ID" as advisor_id,
        nullif(trim("ADVSR_NM"), '') as advisor_name,
        nullif(upper(trim("ROLE_CD")), '') as role_code,
        cast("HIRE_DT" as date) as hire_date,
        cast("TERM_DT" as date) as term_date,
        cast("LAST_UPD_TS" as timestamp with time zone) as last_updated_ts,
        "_batch_id",
        "_loaded_at" as _loaded_at,
        "_source_row" as _source_row
    from {{ source('raw', 'teradata__advsr') }}
),

deduped as (
    select *
    from renamed
    where advisor_id is not null
    qualify row_number() over (
        partition by advisor_id
        order by last_updated_ts desc, _loaded_at desc, _source_row desc
    ) = 1
)

select
    advisor_id,
    advisor_name,
    role_code,
    hire_date,
    term_date,
    last_updated_ts,
    _batch_id
from deduped
