-- Branch dimension (PLAN.md §6.8). Grain is the org seed: one row per branch in
-- reference/org.yaml, including branches the fixture extract does not load.
-- close_date is the latest raw branch row (same grain as stg_branch). A branch
-- with no raw row, or a null close date, is open.
with latest_close as (
    select branch_id, close_date
    from (
        select
            "BRNCH_ID" as branch_id,
            cast("CLOSE_DT" as date) as close_date,
            cast("LAST_UPD_TS" as timestamp with time zone) as last_updated_ts,
            "_loaded_at" as _loaded_at,
            "_source_row" as _source_row
        from {{ source('raw', 'teradata__brnch') }}
    ) as raw_branch
    where branch_id is not null
    qualify row_number() over (
        partition by branch_id
        order by last_updated_ts desc, _loaded_at desc, _source_row desc
    ) = 1
)

select
    md5(org.branch_id) as branch_sk,
    org.branch_id,
    org.branch_name,
    org.district_code,
    org.district_name,
    org.region_code,
    org.region_name,
    org.fsa_code,
    org.province_code,
    cast(org.open_date as date) as open_date,
    latest_close.close_date,
    latest_close.close_date is null as is_open
from {{ ref('org_branch') }} as org
left join latest_close on latest_close.branch_id = org.branch_id
