-- The fixtures' handover (PLAN.md §5): ADV-10014 leaves on 2026-09-28 and PRT-010014 passes
-- to ADV-10013. Its active clients belong to ADV-10014 in W38 and to ADV-10013 in W40, and
-- the transit stays BR-0202 throughout. Returns rows that break this. Fixtures only.
{{ config(enabled=target.name == 'ci') }}

select iso_week_id, client_id, primary_advisor_id, transit_branch_id
from {{ ref('int_client_book_weekly') }}
where portfolio_id = 'PRT-010014'
    and is_active
    and (
        (iso_week_id = '2026-W38' and primary_advisor_id <> 'ADV-10014')
        or (iso_week_id = '2026-W40' and primary_advisor_id <> 'ADV-10013')
        or transit_branch_id <> 'BR-0202'
    )
union all
-- and the check is not vacuous: both weeks have such clients
select week, null, null, null
from (values ('2026-W38'), ('2026-W40')) as w(week)
where not exists (
    select 1 from {{ ref('int_client_book_weekly') }}
    where portfolio_id = 'PRT-010014' and is_active and iso_week_id = w.week
)
