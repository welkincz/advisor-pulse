-- One row per activity_id. Exact duplicates and re-sent updates collapse to the latest
-- updated_ts, then the latest extracted_at (PLAN.md §6.6, DQ010).
with renamed as (
    select
        "ACTIVITY_ID" as activity_id,
        "ADVISOR_ID" as advisor_id,
        "CLIENT_ID" as client_id,
        "BRANCH_ID" as branch_id,
        nullif(upper(trim("ACTIVITY_TYPE")), '') as activity_type,
        nullif(upper(trim("CHANNEL")), '') as channel,
        nullif(upper(trim("STATUS")), '') as status,
        nullif(upper(trim("OUTCOME")), '') as outcome,
        nullif(upper(trim("PRODUCT_LINE")), '') as product_line,
        cast("SCHEDULED_TS" as timestamp with time zone) as scheduled_ts,
        cast("ACTIVITY_TS" as timestamp with time zone) as activity_ts,
        cast("DURATION_MIN" as integer) as duration_min,
        "BOOKED_FROM_ACTIVITY_ID" as booked_from_activity_id,
        cast("CREATED_TS" as timestamp with time zone) as created_ts,
        cast("UPDATED_TS" as timestamp with time zone) as updated_ts,
        cast("_EXTRACTED_AT" as timestamp with time zone) as extracted_at,
        "_batch_id",
        "_loaded_at" as _loaded_at,
        "_source_row" as _source_row
    from {{ source('raw', 'snowflake__activity') }}
),

deduped as (
    select *
    from renamed
    where activity_id is not null
    qualify row_number() over (
        partition by activity_id
        order by updated_ts desc, extracted_at desc, _loaded_at desc, _source_row desc
    ) = 1
)

select
    activity_id,
    advisor_id,
    client_id,
    branch_id,
    activity_type,
    channel,
    status,
    outcome,
    product_line,
    scheduled_ts,
    activity_ts,
    {{ toronto_date('activity_ts') }} as activity_date,
    {{ iso_week_id(toronto_date('activity_ts')) }} as iso_week_id,
    {{ iso_week_id(toronto_date('activity_ts')) }}
        < {{ iso_week_id(toronto_date('extracted_at')) }} as is_late_arriving,
    duration_min,
    booked_from_activity_id,
    created_ts,
    updated_ts,
    extracted_at,
    _batch_id
from deduped
