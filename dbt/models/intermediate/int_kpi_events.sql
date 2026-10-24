-- KPI building blocks (PLAN.md §7), one row per event, each carrying the week it counts
-- in, the branch it is credited to and its additive parts. mart_advisor_weekly and
-- mart_org_weekly aggregate this, so a ratio is always rebuilt from summed parts and
-- distinct clients are counted at each level, never added up.
--
-- Event kinds and the week they count in (America/Toronto dates):
--   completed  completed activity, by activity date
--   scheduled  appointment or review, by SCHEDULED_TS (show rate, conversion)
--   booked     appointment or review, by CREATED_TS (APPT_BOOKED, CALL_TO_APPT)
--   advisor    a non-manager employment range overlaps any day of the week
--   portfolio  an active client in a known portfolio at week end (PRTF_CONTACT_12M),
--              credited to the portfolio's holder at week end and to its transit branch
-- Every other event is credited to the advisor's branch on the date it counts: the
-- activity date, the scheduled date or the booking date. Advisor events use the first
-- non-manager range overlapping the week (week-start branch for existing advisors).
-- Activity with no advisor history on that date (DQ012) stays at its logged branch.
-- Only reported weeks (int_contact_window) get rows: a warm-up year feeds the 12-month
-- window through int_client_contact_12m, not through these events.
with activity as (
    select * from {{ ref('int_activity_enriched') }}
),

activity_type as (
    select * from {{ ref('dim_activity_type') }}
),

history as (
    select * from {{ ref('int_advisor_history') }}
),

weeks as (
    select iso_week_id, min(week_start) as week_start, max(week_end) as week_end
    from {{ ref('dim_date') }}
    where iso_week_id between (select min(iso_week_id) from activity)
        and (select max(iso_week_id) from activity)
        and iso_week_id in (select iso_week_id from {{ ref('int_contact_window') }} where is_reported)
    group by iso_week_id
),

roster as (
    select weeks.iso_week_id, weeks.week_end, history.advisor_id, history.branch_id
    from weeks
    inner join history
        on history.valid_from <= weeks.week_end
        and history.valid_to > weeks.week_start
    where history.role_code <> 'BR_MGR'
    -- Transfers and promotions can produce several overlapping ranges. Count a person
    -- once, retaining the week-start branch or their first eligible branch that week.
    qualify row_number() over (
        partition by weeks.iso_week_id, history.advisor_id
        order by history.valid_from, history.assignment_id
    ) = 1
),

completed as (
    select
        activity.iso_week_id,
        case when activity.is_advisor_matched then activity.advisor_id end as advisor_id,
        activity.attributed_branch_id as branch_id,
        'completed' as event_kind,
        1 as activities_completed,
        case when activity.activity_type = 'CALL_OUT' then 1 else 0 end as calls_out,
        case when activity.activity_type = 'CALL_IN' then 1 else 0 end as calls_in,
        0 as appointments_booked,
        0 as booked_from_call,
        0 as appointments_held,
        0 as no_shows,
        0 as conversions,
        case when activity_type.is_appointment_like then activity.duration_min else 0 end as meeting_minutes,
        case when activity_type.is_appointment_like then 1 else 0 end as meetings_held,
        case when activity_type.counts_as_contact then activity.client_id end as contacted_client_id,
        0 as active_advisors,
        0 as portfolio_clients,
        0 as portfolio_contacted_12m
    from activity
    inner join activity_type using (activity_type)
    where activity.status = 'COMPLETED'
),

meetings as (
    select
        activity.*,
        {{ toronto_date('activity.scheduled_ts') }} as scheduled_date,
        {{ toronto_date('activity.created_ts') }} as created_date
    from activity
    inner join activity_type using (activity_type)
    where activity_type.is_appointment_like
),

scheduled as (
    select
        {{ iso_week_id('meetings.scheduled_date') }} as iso_week_id,
        case when meetings.is_advisor_matched then meetings.advisor_id end as advisor_id,
        coalesce(history.branch_id, meetings.attributed_branch_id) as branch_id,
        'scheduled' as event_kind,
        0, 0, 0, 0, 0,
        case when meetings.status = 'COMPLETED' then 1 else 0 end,
        case when meetings.status = 'NO_SHOW' then 1 else 0 end,
        case when meetings.status = 'COMPLETED' and meetings.outcome in ('PLAN_CREATED', 'PRODUCT_OPENED') then 1 else 0 end,
        0, 0, cast(null as varchar), 0, 0, 0
    from meetings
    left join history
        on meetings.is_advisor_matched
        and history.advisor_id = meetings.advisor_id
        and meetings.scheduled_date >= history.valid_from
        and meetings.scheduled_date < history.valid_to
    where meetings.scheduled_ts is not null
),

booked as (
    select
        {{ iso_week_id('meetings.created_date') }} as iso_week_id,
        case when meetings.is_advisor_matched then meetings.advisor_id end as advisor_id,
        coalesce(history.branch_id, meetings.attributed_branch_id) as branch_id,
        'booked' as event_kind,
        0, 0, 0,
        1,
        case when meetings.booked_from_activity_id is not null then 1 else 0 end,
        0, 0, 0, 0, 0, cast(null as varchar), 0, 0, 0
    from meetings
    left join history
        on meetings.is_advisor_matched
        and history.advisor_id = meetings.advisor_id
        and meetings.created_date >= history.valid_from
        and meetings.created_date < history.valid_to
),

advisor as (
    select
        iso_week_id, advisor_id, branch_id, 'advisor' as event_kind,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, cast(null as varchar),
        1, 0, 0
    from roster
),

portfolio as (
    select
        iso_week_id,
        advisor_id,
        transit_branch_id as branch_id,
        'portfolio' as event_kind,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, cast(null as varchar),
        0,
        1,
        case when contacted_12m then 1 else 0 end
    from {{ ref('int_client_contact_12m') }}
    where iso_week_id in (select iso_week_id from weeks)
)

select * from completed where iso_week_id in (select iso_week_id from weeks)
union all select * from scheduled where iso_week_id in (select iso_week_id from weeks)
union all select * from booked where iso_week_id in (select iso_week_id from weeks)
union all select * from advisor
union all select * from portfolio
