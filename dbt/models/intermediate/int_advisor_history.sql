-- SCD2 ranges built from assignment events, not dbt snapshots (ADR 0001): the same
-- events always give the same ranges, so a full backfill rebuild is deterministic.
-- Each non-TERM event opens a range that runs until the advisor's next event. A TERM
-- event opens nothing, so it closes the last range on the termination date.
with events as (
    select
        assignment_id,
        advisor_id,
        branch_id,
        role_code,
        reason_code,
        effective_date
    from {{ ref('stg_advisor_assignment') }}
    where advisor_id is not null and effective_date is not null
),

-- Two events on one day for one advisor: the later assignment_id wins, so ranges never
-- have zero length.
one_per_day as (
    select *
    from events
    qualify row_number() over (
        partition by advisor_id, effective_date
        order by assignment_id desc
    ) = 1
),

ranged as (
    select
        *,
        lead(effective_date) over (
            partition by advisor_id
            order by effective_date
        ) as next_effective_date
    from one_per_day
)

select
    advisor_id,
    branch_id,
    role_code,
    reason_code as change_reason,
    effective_date as valid_from,
    coalesce(next_effective_date, date '9999-12-31') as valid_to,
    assignment_id
from ranged
where reason_code <> 'TERM'
