-- One row per assignment event. Events stay as events (not collapsed to the current
-- assignment); downstream SCD2 orders them by effective_date (PLAN.md §6.6).
with renamed as (
    select
        "ASGN_ID" as assignment_id,
        "ADVSR_ID" as advisor_id,
        "BRNCH_ID" as branch_id,
        nullif(upper(trim("ROLE_CD")), '') as role_code,
        cast("EFF_DT" as date) as effective_date,
        nullif(upper(trim("RSN_CD")), '') as reason_code,
        cast("LAST_UPD_TS" as timestamp with time zone) as last_updated_ts,
        "_batch_id",
        "_loaded_at" as _loaded_at,
        "_source_row" as _source_row
    from {{ source('raw', 'teradata__advsr_asgn') }}
),

deduped as (
    select *
    from renamed
    where assignment_id is not null
    qualify row_number() over (
        partition by assignment_id
        order by last_updated_ts desc, _loaded_at desc, _source_row desc
    ) = 1
)

select
    assignment_id,
    advisor_id,
    branch_id,
    role_code,
    effective_date,
    reason_code,
    last_updated_ts,
    _batch_id
from deduped
