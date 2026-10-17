-- FSA × ISO week client coverage (PLAN.md §6.8), exported as geo_weekly.parquet (the
-- export keeps the last 13 weeks). Clients are the active book at week end, placed by the
-- FSA on that week's client version and the district of their home branch. Coverage
-- counts a completed activity by anyone in the trailing 13 weeks, as in COVERAGE_13W.
with weeks as (
    select dim_date.iso_week_id, max(dim_date.week_end) as week_end
    from {{ ref('dim_date') }} as dim_date
    where dim_date.iso_week_id in (select iso_week_id from {{ ref('mart_org_weekly') }})
    group by dim_date.iso_week_id
),

completed as (
    select client_id, activity_date, iso_week_id
    from {{ ref('int_activity_enriched') }}
    where status = 'COMPLETED' and client_id is not null
),

clients as (
    select
        weeks.iso_week_id,
        book.client_id,
        book.fsa_code,
        org.district_code,
        exists (
            select 1
            from completed
            where completed.client_id = book.client_id
                and completed.activity_date between weeks.week_end - 90 and weeks.week_end
        ) as is_contacted_13w,
        (
            select count(*)
            from completed
            where completed.client_id = book.client_id
                and completed.iso_week_id = weeks.iso_week_id
        ) as activities_completed
    from weeks
    inner join {{ ref('int_client_book_weekly') }} as book
        on book.iso_week_id = weeks.iso_week_id
    inner join {{ ref('dim_org') }} as org
        on org.branch_id = book.primary_branch_id
    where book.is_active
)

select
    iso_week_id,
    fsa_code,
    district_code,
    cast(count(*) as bigint) as active_clients,
    cast(count(*) filter (where is_contacted_13w) as bigint) as clients_contacted_13w,
    round(count(*) filter (where is_contacted_13w) / count(*), 4) as coverage_rate_13w,
    cast(sum(activities_completed) as bigint) as activities_completed
from clients
group by iso_week_id, fsa_code, district_code
