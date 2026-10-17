-- DQ022: at every level and week, each additive measure on a node equals the sum over its
-- children (distinct clients are not additive and are excluded). Returns each mismatch.
with org as (
    select * from {{ ref('mart_org_weekly') }}
),

children as (
    select
        child.iso_week_id,
        child.parent_id,
        sum(child.active_advisors) as active_advisors,
        sum(child.activities_completed) as activities_completed,
        sum(child.calls_out) as calls_out,
        sum(child.calls_in) as calls_in,
        sum(child.appointments_booked) as appointments_booked,
        sum(child.appointments_held) as appointments_held,
        sum(child.no_shows) as no_shows,
        sum(child.conversions) as conversions,
        sum(child.book_size) as book_size,
        sum(child.clients_covered_13w) as clients_covered_13w
    from org as child
    where child.parent_id is not null
    group by child.iso_week_id, child.parent_id
)

select parent.iso_week_id, parent.level, parent.node_id
from org as parent
left join children
    on children.iso_week_id = parent.iso_week_id and children.parent_id = parent.node_id
where parent.level <> 'BRANCH'
    and (parent.active_advisors <> coalesce(children.active_advisors, 0)
    or parent.activities_completed <> coalesce(children.activities_completed, 0)
    or parent.calls_out <> coalesce(children.calls_out, 0)
    or parent.calls_in <> coalesce(children.calls_in, 0)
    or parent.appointments_booked <> coalesce(children.appointments_booked, 0)
    or parent.appointments_held <> coalesce(children.appointments_held, 0)
    or parent.no_shows <> coalesce(children.no_shows, 0)
    or parent.conversions <> coalesce(children.conversions, 0)
    or parent.book_size <> coalesce(children.book_size, 0)
    or parent.clients_covered_13w <> coalesce(children.clients_covered_13w, 0))
