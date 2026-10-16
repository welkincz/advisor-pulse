-- Advisor SCD2 dimension (PLAN.md §6.8) with the Unknown member that unmatched activity
-- maps to (DQ012). advisor_sk hashes the natural key, so it survives full rebuilds.
with history as (
    select * from {{ ref('int_advisor_history') }}
),

advisor as (
    select * from {{ ref('stg_advisor') }}
),

branch as (
    select * from {{ ref('stg_branch') }}
),

scd2 as (
    select
        md5(history.advisor_id || '|' || strftime(history.valid_from, '%Y-%m-%d'))
            as advisor_sk,
        history.advisor_id,
        coalesce(advisor.advisor_name, 'Unknown advisor') as advisor_name,
        history.role_code,
        history.branch_id,
        branch.district_code,
        branch.region_code,
        history.valid_from,
        history.valid_to,
        history.valid_to = date '9999-12-31' as is_current,
        history.change_reason,
        advisor.hire_date,
        advisor.term_date
    from history
    left join advisor on history.advisor_id = advisor.advisor_id
    left join branch on history.branch_id = branch.branch_id
),

unknown_member as (
    select
        'UNKNOWN' as advisor_sk,
        'UNKNOWN' as advisor_id,
        'Unknown advisor' as advisor_name,
        cast(null as varchar) as role_code,
        cast(null as varchar) as branch_id,
        cast(null as varchar) as district_code,
        cast(null as varchar) as region_code,
        date '1900-01-01' as valid_from,
        date '9999-12-31' as valid_to,
        true as is_current,
        cast(null as varchar) as change_reason,
        cast(null as date) as hire_date,
        cast(null as date) as term_date
)

select * from scd2
union all
select * from unknown_member
