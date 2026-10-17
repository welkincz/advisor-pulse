-- Reconcile the fact with the fixture's expected marts: per advisor × week, completed
-- activities and calls, credited to the as-of branch, must equal
-- fixtures/exports/advisor_weekly.parquet (PLAN.md §7).
{{ config(enabled=target.name == 'ci') }}

with expected as (
    select iso_week_id, advisor_id, md5(branch_id) as branch_sk, activities_completed, calls_out, calls_in
    from read_parquet('fixtures/exports/advisor_weekly.parquet')
),

actual as (
    select
        iso_week_id,
        advisor_id,
        branch_sk,
        count(*) filter (where is_completed) as activities_completed,
        count(*) filter (where is_completed and activity_type = 'CALL_OUT') as calls_out,
        count(*) filter (where is_completed and activity_type = 'CALL_IN') as calls_in
    from {{ ref('fct_activity') }}
    where advisor_sk <> 'UNKNOWN'
        and iso_week_id in (select iso_week_id from expected)
    group by iso_week_id, advisor_id, branch_sk
)

select *
from (
    select
        coalesce(expected.iso_week_id, actual.iso_week_id) as iso_week_id,
        coalesce(expected.advisor_id, actual.advisor_id) as advisor_id,
        expected.branch_sk as expected_branch_sk,
        actual.branch_sk as actual_branch_sk,
        expected.activities_completed as expected_completed,
        actual.activities_completed as actual_completed,
        expected.calls_out as expected_calls_out,
        actual.calls_out as actual_calls_out,
        expected.calls_in as expected_calls_in,
        actual.calls_in as actual_calls_in
    from expected
    full outer join actual using (iso_week_id, advisor_id, branch_sk)
) as compared
where coalesce(expected_completed, 0) <> coalesce(actual_completed, 0)
    or coalesce(expected_calls_out, 0) <> coalesce(actual_calls_out, 0)
    or coalesce(expected_calls_in, 0) <> coalesce(actual_calls_in, 0)

union all

select null, null, null, null, null, null, null, null, null, null
where (select count(*) from expected) = 0
