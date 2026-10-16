-- Checks fixture ground truth, so it runs only on the ci target (make dbt-build-ci).
{{ config(enabled=target.name == 'ci') }}
-- Every HR event in fixtures/defects.json changes SCD2 exactly as recorded: the prior range
-- (raw_value) closes on the effective date, and a transfer or promotion opens one new range
-- (expected_value) that day; a TERM opens none. Returns one row per mismatch.
with events as (
    select
        defect.kind,
        defect.natural_key as assignment_id,
        defect.raw_value as before_value,
        defect.expected_value as after_value
    from (
        select unnest(defects) as defect
        from read_json('fixtures/defects.json')
    )
    where defect.kind in ('ADVISOR_TRANSFER', 'ADVISOR_PROMOTION', 'ADVISOR_TERM')
),

dated as (
    select events.*, asg.advisor_id, asg.effective_date
    from events
    inner join {{ ref('stg_advisor_assignment') }} as asg using (assignment_id)
),

checked as (
    select
        dated.*,
        prior.branch_id as prior_branch,
        prior.role_code as prior_role,
        opened.branch_id as new_branch,
        opened.role_code as new_role
    from dated
    left join {{ ref('int_advisor_history') }} as prior
        on dated.advisor_id = prior.advisor_id and prior.valid_to = dated.effective_date
    left join {{ ref('int_advisor_history') }} as opened
        on dated.advisor_id = opened.advisor_id and opened.valid_from = dated.effective_date
)

select *
from checked
where
    (kind = 'ADVISOR_TRANSFER' and (prior_branch is distinct from before_value
        or new_branch is distinct from after_value))
    or (kind = 'ADVISOR_PROMOTION' and (prior_role is distinct from before_value
        or new_role is distinct from after_value))
    or (kind = 'ADVISOR_TERM' and (prior_branch is distinct from before_value
        or new_branch is not null))

union all

select 'MISSING_EVENTS', null, null, null, null, null, null, null, null, null
where (select count(*) from dated) <> 4
