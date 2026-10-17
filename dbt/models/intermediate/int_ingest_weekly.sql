-- Ingest batch counts per ISO week (PLAN.md §7 LATE_RATE and QUAR_RATE, §8 DQ001–DQ012),
-- for mart_dq_weekly and the national operational KPIs in mart_weekly_report.
--
-- A file belongs to the week of the date in its name (contracts.sources):
-- snowflake/activity/extract_date=YYYY-MM-DD/ and teradata/client_YYYYMMDD.csv. The CLNT
-- snapshot (edw.sqlite) has no date and belongs to the first activity week of the run
-- that loaded it, which is how the fixtures and a backfill's first week read it.
-- Rows read include quarantined rows; per-row counts are over rows that were loaded.
with manifest as (
    select
        file_path,
        batch_id,
        run_id,
        table_name,
        row_count,
        case
            when regexp_matches(file_path, 'extract_date=\d{4}-\d{2}-\d{2}/')
                then cast(regexp_extract(file_path, 'extract_date=(\d{4}-\d{2}-\d{2})/', 1) as date)
            when regexp_matches(file_path, 'client_\d{8}\.csv$')
                then cast(strptime(regexp_extract(file_path, 'client_(\d{8})\.csv$', 1), '%Y%m%d') as date)
        end as file_date
    from {{ source('meta', 'load_manifest') }}
    where status = 'LOADED' and table_name in ('activity', 'CLNT')
),

files as (
    select
        manifest.*,
        coalesce(
            {{ iso_week_id('file_date') }},
            min(case when table_name = 'activity' then {{ iso_week_id('file_date') }} end)
                over (partition by run_id)
        ) as iso_week_id
    from manifest
),

quarantined as (
    select
        files.iso_week_id,
        count(*) filter (where rejected.rule_id = 'DQ001') as dq001_rows,
        count(*) filter (where rejected.rule_id = 'DQ002') as dq002_rows,
        count(*) filter (where rejected.rule_id = 'DQ003') as dq003_rows,
        count(*) filter (where rejected.rule_id = 'DQ004') as dq004_rows,
        count(*) filter (where rejected.rule_id = 'DQ005') as dq005_rows,
        count(*) filter (where files.table_name = 'activity') as activity_quarantined,
        count(*) filter (where files.table_name = 'CLNT') as client_quarantined
    from {{ source('quarantine', 'rejected_rows') }} as rejected
    inner join files on rejected.batch_id = files.batch_id
    group by files.iso_week_id
),

-- Every loaded activity row, in load order. A row whose activity_id was already loaded
-- (an exact copy or a re-sent version) is one staging collapses (DQ010).
loaded as (
    select
        files.iso_week_id,
        raw."ADVISOR_ID" as advisor_id,
        {{ iso_week_id(toronto_date('raw."ACTIVITY_TS"')) }} as activity_week,
        row_number() over (
            partition by raw."ACTIVITY_ID"
            order by files.iso_week_id, raw._source_file, raw._source_row
        ) as load_order
    from {{ source('raw', 'snowflake__activity') }} as raw
    inner join files on raw._batch_id = files.batch_id
),

loaded_counts as (
    select
        iso_week_id,
        count(*) as activity_loaded,
        count(*) filter (where activity_week < iso_week_id) as late_rows,
        count(*) filter (where load_order > 1) as dedupe_rows,
        count(*) filter (
            where advisor_id is null
                or advisor_id not in (select advisor_id from {{ ref('stg_advisor') }})
        ) as unknown_advisor_rows
    from loaded
    group by iso_week_id
),

read_counts as (
    select
        iso_week_id,
        sum(row_count) filter (where table_name = 'activity') as activity_rows,
        sum(row_count) filter (where table_name = 'CLNT') as client_rows
    from files
    group by iso_week_id
)

select
    read_counts.iso_week_id,
    cast(coalesce(read_counts.activity_rows, 0) as bigint) as activity_rows,
    cast(coalesce(loaded_counts.activity_loaded, 0) as bigint) as activity_loaded,
    cast(coalesce(quarantined.activity_quarantined, 0) as bigint) as activity_quarantined,
    cast(coalesce(quarantined.dq001_rows, 0) as bigint) as dq001_rows,
    cast(coalesce(quarantined.dq002_rows, 0) as bigint) as dq002_rows,
    cast(coalesce(quarantined.dq003_rows, 0) as bigint) as dq003_rows,
    cast(coalesce(quarantined.dq004_rows, 0) as bigint) as dq004_rows,
    cast(coalesce(loaded_counts.late_rows, 0) as bigint) as late_rows,
    cast(coalesce(loaded_counts.dedupe_rows, 0) as bigint) as dedupe_rows,
    cast(coalesce(loaded_counts.unknown_advisor_rows, 0) as bigint) as unknown_advisor_rows,
    cast(coalesce(read_counts.client_rows, 0) as bigint) as client_rows,
    cast(coalesce(quarantined.client_quarantined, 0) as bigint) as client_quarantined,
    cast(coalesce(quarantined.dq005_rows, 0) as bigint) as dq005_rows
from read_counts
left join quarantined using (iso_week_id)
left join loaded_counts using (iso_week_id)
