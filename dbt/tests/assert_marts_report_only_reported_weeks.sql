-- Every weekly mart starts at the report start (int_contact_window.is_reported, #273): a
-- warm-up year before it feeds the 12-month window but is never a reported week.
with marts as (
    select distinct 'mart_org_weekly' as model, iso_week_id from {{ ref('mart_org_weekly') }}
    union all
    select distinct 'mart_advisor_weekly', iso_week_id from {{ ref('mart_advisor_weekly') }}
    union all
    select distinct 'mart_weekly_report', iso_week_id from {{ ref('mart_weekly_report') }}
    union all
    select distinct 'mart_dq_weekly', iso_week_id from {{ ref('mart_dq_weekly') }}
    union all
    select distinct 'mart_geo_weekly', iso_week_id from {{ ref('mart_geo_weekly') }}
)

select marts.model, marts.iso_week_id
from marts
inner join {{ ref('int_contact_window') }} as contact_window using (iso_week_id)
where not contact_window.is_reported
