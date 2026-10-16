-- The active book is the coverage denominator. On the ci target it has to match
-- book_size in fixtures/exports/advisor_weekly.parquet (PLAN.md §7, per advisor × week).
{{ config(enabled=target.name == 'ci') }}

with expected as (
    select iso_week_id, advisor_id, book_size
    from read_parquet('fixtures/exports/advisor_weekly.parquet')
),

actual as (
    select
        iso_week_id,
        primary_advisor_id as advisor_id,
        count(*) as book_size
    from {{ ref('int_client_book_weekly') }}
    where is_active
        and iso_week_id in (select iso_week_id from expected)
    group by iso_week_id, primary_advisor_id
)

select
    coalesce(expected.iso_week_id, actual.iso_week_id) as iso_week_id,
    coalesce(expected.advisor_id, actual.advisor_id) as advisor_id,
    expected.book_size as expected_book_size,
    actual.book_size as actual_book_size
from expected
full outer join actual using (iso_week_id, advisor_id)
where coalesce(expected.book_size, 0) <> coalesce(actual.book_size, 0)

union all

select null, null, null, null
where (select count(*) from expected) = 0
