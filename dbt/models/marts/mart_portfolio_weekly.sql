-- Portfolio × ISO week for the lead KPI (PLAN.md §6.8, §7), exported as
-- portfolio_weekly.parquet (last 26 weeks). Each portfolio is shown under its holder at
-- week end and its transit; holder_branch_id is where that holder works that day, so a
-- portfolio whose holder sits elsewhere (DQ025) is visible, and tested, here.
with clients as (
    select * from {{ ref('int_client_contact_12m') }}
),

portfolios as (
    select
        iso_week_id,
        week_end,
        portfolio_id,
        advisor_id,
        transit_branch_id,
        count(*) as clients,
        count(*) filter (where contacted_12m) as contacted_12m
    from clients
    group by iso_week_id, week_end, portfolio_id, advisor_id, transit_branch_id
)

select
    portfolios.iso_week_id,
    portfolios.portfolio_id,
    portfolios.advisor_id,
    portfolios.transit_branch_id as branch_id,
    org.district_code,
    org.region_code,
    holder.branch_id as holder_branch_id,
    cast(portfolios.clients as bigint) as clients,
    cast(portfolios.contacted_12m as bigint) as contacted_12m,
    case when contact_window.is_window_complete then
        round(portfolios.contacted_12m / portfolios.clients, 4)
    end as contacted_rate_12m
from portfolios
inner join {{ ref('dim_org') }} as org on org.branch_id = portfolios.transit_branch_id
inner join {{ ref('int_contact_window') }} as contact_window using (iso_week_id)
left join {{ ref('int_advisor_history') }} as holder
    on holder.advisor_id = portfolios.advisor_id
    and portfolios.week_end >= holder.valid_from
    and portfolios.week_end < holder.valid_to
where portfolios.iso_week_id in (select iso_week_id from {{ ref('mart_org_weekly') }})
