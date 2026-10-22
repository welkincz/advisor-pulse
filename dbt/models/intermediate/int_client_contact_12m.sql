-- The lead KPI's building block (PLAN.md §7, PRTF_CONTACT_12M): one row per active client
-- in a known portfolio at week end, with the last completed contact by ANY advisor on or
-- before that day. An ASOF join finds it in one pass instead of scanning a year per week.
with contacts as (
    select distinct activity.client_id, activity.activity_date
    from {{ ref('int_activity_enriched') }} as activity
    inner join {{ ref('dim_activity_type') }} as activity_type using (activity_type)
    where activity.status = 'COMPLETED'
        and activity.client_id is not null
        and activity_type.counts_as_contact
),

book as (
    select client_id, iso_week_id, week_end, portfolio_id, primary_advisor_id, transit_branch_id
    from {{ ref('int_client_book_weekly') }}
    where is_active and transit_branch_id is not null
)

select
    book.client_id,
    book.iso_week_id,
    book.week_end,
    book.portfolio_id,
    book.primary_advisor_id as advisor_id,
    book.transit_branch_id,
    contacts.activity_date as last_contact_date,
    coalesce(contacts.activity_date > cast(book.week_end - interval 12 month as date), false)
        as contacted_12m
from book
asof left join contacts
    on contacts.client_id = book.client_id
    and book.week_end >= contacts.activity_date
