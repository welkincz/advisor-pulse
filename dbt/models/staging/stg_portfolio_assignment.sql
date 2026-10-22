-- One row per portfolio assignment event (PLAN.md §6.2, §6.6). Events stay events;
-- int_portfolio_history orders them into holder ranges.
with renamed as (
    select
        "PASGN_ID" as portfolio_assignment_id,
        "PRTF_ID" as portfolio_id,
        "ADVSR_ID" as advisor_id,
        cast("EFF_DT" as date) as effective_date,
        nullif(upper(trim("RSN_CD")), '') as reason_code,
        cast("LAST_UPD_TS" as timestamp with time zone) as last_updated_ts,
        "_loaded_at" as _loaded_at,
        "_source_row" as _source_row
    from {{ source('raw', 'teradata__prtf_asgn') }}
)

select
    portfolio_assignment_id, portfolio_id, advisor_id, effective_date, reason_code,
    last_updated_ts
from renamed
where portfolio_assignment_id is not null
qualify row_number() over (
    partition by portfolio_assignment_id
    order by last_updated_ts desc, _loaded_at desc, _source_row desc
) = 1
