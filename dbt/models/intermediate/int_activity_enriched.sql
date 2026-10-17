-- One row per activity, joined to the advisor history range in force on the activity date
-- (PLAN.md §6.7, §7 attribution): the branch is where the advisor sat then, not now.
-- An advisor with no range on that date (DQ012) keeps the source branch and no history.
with activity as (
    select * from {{ ref('stg_activity') }}
),

history as (
    select * from {{ ref('int_advisor_history') }}
),

client as (
    select client_id, fsa_code from {{ ref('stg_client') }}
)

select
    activity.activity_id,
    activity.activity_date,
    activity.iso_week_id,
    activity.advisor_id,
    history.valid_from as advisor_valid_from,
    history.advisor_id is not null as is_advisor_matched,
    activity.branch_id as source_branch_id,
    coalesce(history.branch_id, activity.branch_id) as attributed_branch_id,
    activity.client_id,
    client.client_id is not null as is_client_matched,
    coalesce(client.fsa_code, 'UNK') as fsa_code,
    activity.activity_type,
    activity.channel,
    activity.status,
    activity.outcome,
    activity.product_line,
    activity.scheduled_ts,
    activity.activity_ts,
    activity.created_ts,
    activity.duration_min,
    activity.is_late_arriving,
    activity.booked_from_activity_id,
    activity._batch_id
from activity
left join history
    on activity.advisor_id = history.advisor_id
    and activity.activity_date >= history.valid_from
    and activity.activity_date < history.valid_to
left join client on activity.client_id = client.client_id
