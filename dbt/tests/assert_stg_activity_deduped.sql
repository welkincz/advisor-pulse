-- DQ010 on fixtures: every duplicate defect in fixtures/defects.json is one staged row,
-- and a re-sent update keeps the status of the latest version. Returns one row per failure.
-- `make dbt-build-ci` runs from the repo root, where fixtures/defects.json lives.
with defects as (
    select
        defect.kind,
        defect.natural_key as activity_id,
        defect.expected_value
    from (
        select unnest(defects) as defect
        from read_json('fixtures/defects.json')
    )
    where defect.rule_id = 'DQ010'
),

raw_counts as (
    select "ACTIVITY_ID" as activity_id, count(*) as raw_rows
    from {{ source('raw', 'snowflake__activity') }}
    group by 1
),

staged as (
    select activity_id, max(status) as status, count(*) as staged_rows
    from {{ ref('stg_activity') }}
    group by 1
)

select
    defects.kind,
    defects.activity_id,
    defects.expected_value,
    staged.status as staged_status,
    staged.staged_rows,
    raw_counts.raw_rows
from defects
left join staged on staged.activity_id = defects.activity_id
left join raw_counts on raw_counts.activity_id = defects.activity_id
where
    staged.activity_id is null
    or staged.staged_rows <> 1
    or raw_counts.raw_rows < 2
    or (
        defects.kind = 'RESENT_UPDATE'
        and staged.status is distinct from defects.expected_value
    )

union all

select
    'MISSING_MANIFEST' as kind,
    null as activity_id,
    null as expected_value,
    null as staged_status,
    null as staged_rows,
    null as raw_rows
where (select count(*) from defects) = 0
