-- Fixture ground truth for the client book. Runs only on the ci target.
{{ config(enabled=target.name == 'ci') }}
-- A CLIENT_REASSIGNMENT in fixtures/defects.json is under raw_value (the old advisor)
-- for every week whose Sunday is before the file date, and under expected_value after.
-- A status flip to C drops the client (`is_active` false) from the week whose Sunday
-- is on or after the Toronto date of that update, and they stay out. The fixture
-- closure is Sunday 2026-09-13, so that client is active in 2026-W36 and inactive
-- from 2026-W37 on (PLAN.md §7: active book at week end).
with defects as (
    select
        defect.natural_key as client_id,
        defect.raw_value as old_advisor_id,
        defect.expected_value as new_advisor_id,
        cast(
            strptime(regexp_extract(defect.file, 'client_([0-9]{8})\.csv', 1), '%Y%m%d') as date
        ) as effective_date
    from (
        select unnest(defects) as defect
        from read_json('fixtures/defects.json')
    )
    where defect.kind = 'CLIENT_REASSIGNMENT'
),

book as (
    select * from {{ ref('int_client_book_weekly') }}
),

reassignment_failures as (
    select
        defects.client_id,
        'reassignment' as check_name,
        defects.effective_date,
        defects.old_advisor_id,
        defects.new_advisor_id,
        book.iso_week_id,
        book.week_end,
        book.primary_advisor_id,
        book.is_active
    from defects
    inner join book on book.client_id = defects.client_id
    where
        (
            book.week_end < defects.effective_date
            and (
                book.primary_advisor_id is distinct from defects.old_advisor_id
                or not book.is_active
            )
        )
        or (
            book.week_end >= defects.effective_date
            and (
                book.primary_advisor_id is distinct from defects.new_advisor_id
                or not book.is_active
            )
        )
),

raw_versions as (
    select
        "CLNT_ID" as client_id,
        nullif(upper(trim("STAT_CD")), '') as status_code,
        cast("LAST_UPD_TS" as timestamp with time zone) as last_updated_ts,
        "_loaded_at" as _loaded_at,
        "_source_file" as _source_file,
        "_source_row" as _source_row
    from {{ source('raw', 'teradata__clnt') }}
    where "CLNT_ID" is not null and "LAST_UPD_TS" is not null
    qualify row_number() over (
        partition by client_id, last_updated_ts
        order by _loaded_at desc, _source_file desc, _source_row desc
    ) = 1
),

ordered as (
    select
        client_id,
        status_code,
        last_updated_ts,
        lag(status_code) over (
            partition by client_id
            order by last_updated_ts
        ) as prior_status
    from raw_versions
),

closures as (
    select
        client_id,
        min({{ toronto_date('last_updated_ts') }}) as closure_date
    from ordered
    where status_code = 'C' and prior_status = 'A'
    group by client_id
),

closure_failures as (
    select
        closures.client_id,
        'closure' as check_name,
        closures.closure_date as effective_date,
        cast(null as varchar) as old_advisor_id,
        cast(null as varchar) as new_advisor_id,
        book.iso_week_id,
        book.week_end,
        book.primary_advisor_id,
        book.is_active
    from closures
    inner join book on book.client_id = closures.client_id
    where
        (book.week_end < closures.closure_date and not book.is_active)
        or (book.week_end >= closures.closure_date and book.is_active)
),

never_active as (
    select client_id
    from ordered
    group by client_id
    having not bool_or(status_code = 'A')
),

never_active_failures as (
    select
        book.client_id,
        'already_closed' as check_name,
        cast(null as date) as effective_date,
        cast(null as varchar) as old_advisor_id,
        cast(null as varchar) as new_advisor_id,
        book.iso_week_id,
        book.week_end,
        book.primary_advisor_id,
        book.is_active
    from never_active
    inner join book on book.client_id = never_active.client_id
    where book.is_active
),

current_advisor as (
    select
        defects.client_id,
        'dim_client_advisor' as check_name,
        defects.effective_date,
        defects.old_advisor_id,
        defects.new_advisor_id,
        cast(null as varchar) as iso_week_id,
        cast(null as date) as week_end,
        dim.primary_advisor_id,
        dim.is_active
    from defects
    left join {{ ref('dim_client') }} as dim on dim.client_id = defects.client_id
    where dim.primary_advisor_id is distinct from defects.new_advisor_id
        or not coalesce(dim.is_active, false)
),

current_closure as (
    select
        closures.client_id,
        'dim_client_closed' as check_name,
        closures.closure_date as effective_date,
        cast(null as varchar) as old_advisor_id,
        cast(null as varchar) as new_advisor_id,
        cast(null as varchar) as iso_week_id,
        cast(null as date) as week_end,
        dim.primary_advisor_id,
        dim.is_active
    from closures
    left join {{ ref('dim_client') }} as dim on dim.client_id = closures.client_id
    where dim.client_id is null or dim.is_active
)

select * from reassignment_failures
union all
select * from closure_failures
union all
select * from never_active_failures
union all
select * from current_advisor
union all
select * from current_closure
union all
select
    cast(null as varchar),
    'missing_reassignments',
    cast(null as date),
    cast(null as varchar),
    cast(null as varchar),
    cast(null as varchar),
    cast(null as date),
    cast(null as varchar),
    cast(null as boolean)
where (select count(*) from defects) = 0
union all
select
    cast(null as varchar),
    'missing_closures',
    cast(null as date),
    cast(null as varchar),
    cast(null as varchar),
    cast(null as varchar),
    cast(null as date),
    cast(null as varchar),
    cast(null as boolean)
where (select count(*) from closures) = 0
union all
-- The week before and the week of each reassignment must both exist.
select
    defects.client_id,
    'missing_before_week',
    defects.effective_date,
    defects.old_advisor_id,
    defects.new_advisor_id,
    cast(null as varchar),
    cast(null as date),
    cast(null as varchar),
    cast(null as boolean)
from defects
where not exists (
    select 1
    from book
    where book.client_id = defects.client_id
        and book.week_end < defects.effective_date
)
or not exists (
    select 1
    from book
    where book.client_id = defects.client_id
        and book.week_end >= defects.effective_date
)
