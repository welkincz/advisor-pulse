-- Ratios are rebuilt from summed parts after the roll-up, never averaged: national show
-- rate = Σ held ÷ Σ (held + no-show) over branches, and the same for conversion and
-- call-to-appointment. Returns each week where the national value differs.
with branch as (
    select
        iso_week_id,
        sum(appointments_held) as held,
        sum(no_shows) as no_shows,
        sum(conversions) as conversions
    from {{ ref('mart_org_weekly') }}
    where level = 'BRANCH'
    group by iso_week_id
),

national as (
    select * from {{ ref('mart_org_weekly') }} where level = 'NATIONAL'
)

select national.iso_week_id, national.show_rate, branch.held, branch.no_shows
from national
inner join branch using (iso_week_id)
where national.show_rate is distinct from round(branch.held / nullif(branch.held + branch.no_shows, 0), 4)
    or national.conversion_rate is distinct from round(branch.conversions / nullif(branch.held, 0), 4)
