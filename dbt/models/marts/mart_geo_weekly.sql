-- FSA × ISO week clients and contact (PLAN.md §6.8), exported as geo_weekly.parquet (the
-- export keeps the last 13 weeks). Clients are the active book at week end, placed by the
-- FSA on that week's client version and the district of their home branch. The portfolio
-- columns are the lead KPI's parts (int_client_contact_12m) for the same clients.
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
        portfolio.client_id is not null as in_portfolio,
        coalesce(portfolio.contacted_12m, false) as is_contacted_12m,
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
    left join {{ ref('int_client_contact_12m') }} as portfolio
        on portfolio.client_id = book.client_id
        and portfolio.iso_week_id = book.iso_week_id
    where book.is_active
)

select
    iso_week_id,
    fsa_code,
    district_code,
    cast(count(*) as bigint) as active_clients,
    cast(sum(activities_completed) as bigint) as activities_completed,
    cast(count(*) filter (where in_portfolio) as bigint) as portfolio_clients,
    cast(count(*) filter (where is_contacted_12m) as bigint) as portfolio_contacted_12m,
    case when bool_and(contact_window.is_window_complete) then
        round(count(*) filter (where is_contacted_12m) / nullif(count(*) filter (where in_portfolio), 0), 4)
    end as portfolio_contacted_rate_12m
from clients
inner join {{ ref('int_contact_window') }} as contact_window using (iso_week_id)
group by iso_week_id, fsa_code, district_code
