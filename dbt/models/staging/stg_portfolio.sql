-- One row per portfolio_id, the latest LAST_UPD_TS (PLAN.md §6.2, §6.6). A portfolio
-- belongs to one branch, its transit, for life; who holds it lives in PRTF_ASGN.
with renamed as (
    select
        "PRTF_ID" as portfolio_id,
        nullif(trim("BRNCH_ID"), '') as branch_id,
        cast("OPEN_DT" as date) as open_date,
        cast("CLOSE_DT" as date) as close_date,
        cast("LAST_UPD_TS" as timestamp with time zone) as last_updated_ts,
        "_loaded_at" as _loaded_at,
        "_source_row" as _source_row
    from {{ source('raw', 'teradata__prtf') }}
)

select portfolio_id, branch_id, open_date, close_date, last_updated_ts
from renamed
where portfolio_id is not null
qualify row_number() over (
    partition by portfolio_id
    order by last_updated_ts desc, _loaded_at desc, _source_row desc
) = 1
