-- The quarterly mart agrees with the weekly one: flows summed over a quarter's weeks match,
-- a branch's quarter-end stock is its stock in its own last reported week, and children
-- (flows and stocks) sum to their parent.
with weekly as (
    select
        dim.week_fiscal_quarter_id as fiscal_quarter_id,
        w.level, w.node_id,
        sum(w.activities_completed) as activities_completed,
        sum(w.appointments_held) as appointments_held,
        sum(w.active_advisors) as advisor_weeks,
        max(w.iso_week_id) as own_last_week
    from {{ ref('mart_org_weekly') }} as w
    inner join (select distinct iso_week_id, week_fiscal_quarter_id from {{ ref('dim_date') }}) as dim
        on dim.iso_week_id = w.iso_week_id
    group by 1, 2, 3
),

flow_mismatch as (
    select 'flow' as kind, q.fiscal_quarter_id, q.node_id
    from {{ ref('mart_org_quarterly') }} as q
    inner join weekly using (fiscal_quarter_id, level, node_id)
    where q.activities_completed <> weekly.activities_completed
        or q.appointments_held <> weekly.appointments_held
        or q.advisor_weeks <> weekly.advisor_weeks
),

stock_mismatch as (
    select 'stock', q.fiscal_quarter_id, q.node_id
    from {{ ref('mart_org_quarterly') }} as q
    inner join weekly using (fiscal_quarter_id, level, node_id)
    inner join {{ ref('mart_org_weekly') }} as w
        on w.iso_week_id = weekly.own_last_week and w.level = q.level and w.node_id = q.node_id
    where q.level = 'BRANCH'
        and (q.book_size <> w.book_size or q.clients_covered_13w <> w.clients_covered_13w)
),

children as (
    select
        fiscal_quarter_id, parent_id,
        sum(activities_completed) as activities_completed,
        sum(book_size) as book_size,
        sum(clients_covered_13w) as clients_covered_13w
    from {{ ref('mart_org_quarterly') }}
    where level <> 'NATIONAL'
    group by 1, 2
),

rollup_mismatch as (
    select 'rollup', c.fiscal_quarter_id, c.parent_id
    from children as c
    inner join {{ ref('mart_org_quarterly') }} as p
        on p.fiscal_quarter_id = c.fiscal_quarter_id and p.node_id = c.parent_id
    where p.activities_completed <> c.activities_completed
        or p.book_size <> c.book_size
        or p.clients_covered_13w <> c.clients_covered_13w
)

select * from flow_mismatch
union all select * from stock_mismatch
union all select * from rollup_mismatch
