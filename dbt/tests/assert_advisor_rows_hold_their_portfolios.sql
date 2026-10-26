-- Every portfolio holder with a non-manager employment range overlapping the week has an
-- advisor row that week carrying all of their portfolio clients (#312). Holders off the roster
-- (branch managers, nobody employed that week) count at their portfolio's branch only.
-- The roster is read from int_advisor_history directly, not from the model's own CTE.
-- Returns one row per holder-week whose advisor row is missing or short.
with weeks as (
    select iso_week_id, min(week_start) as week_start, max(week_end) as week_end
    from {{ ref('dim_date') }}
    group by iso_week_id
),

held as (
    select
        iso_week_id,
        advisor_id,
        sum(portfolio_clients) as portfolio_clients,
        sum(portfolio_contacted_12m) as portfolio_contacted_12m
    from {{ ref('int_kpi_events') }}
    where event_kind = 'portfolio' and advisor_id is not null
    group by iso_week_id, advisor_id
),

eligible as (
    select held.*
    from held
    inner join weeks using (iso_week_id)
    where exists (
        select 1
        from {{ ref('int_advisor_history') }} as history
        where history.advisor_id = held.advisor_id
            and history.valid_from <= weeks.week_end
            and history.valid_to > weeks.week_start
            and history.role_code <> 'BR_MGR'
    )
)

select
    eligible.iso_week_id,
    eligible.advisor_id,
    eligible.portfolio_clients as held_clients,
    advisor.portfolio_clients as advisor_row_clients
from eligible
left join {{ ref('mart_advisor_weekly') }} as advisor
    on advisor.iso_week_id = eligible.iso_week_id
    and advisor.advisor_id = eligible.advisor_id
where advisor.advisor_id is null
    or advisor.portfolio_clients <> eligible.portfolio_clients
    or advisor.portfolio_contacted_12m <> eligible.portfolio_contacted_12m
