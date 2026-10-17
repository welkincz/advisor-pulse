-- PLAN.md §7: activity is credited to the advisor's branch on the activity date. The two
-- fixture transfers (defects.json ADVISOR_TRANSFER) must split each advisor's activity at
-- the effective Monday, with activity on both sides.
{{ config(enabled=target.name == 'ci') }}

with transfers as (
    select *
    from (
        values
        ('ADV-10008', date '2026-09-14', 'BR-0102', 'BR-0201'),
        ('ADV-10004', date '2026-09-21', 'BR-0101', 'BR-0102')
    ) as t (advisor_id, effective_date, before_branch, after_branch)
),

credited as (
    select
        transfers.advisor_id,
        fct.activity_id,
        fct.activity_date >= transfers.effective_date as is_after,
        fct.branch_sk,
        md5(case when fct.activity_date >= transfers.effective_date then after_branch else before_branch end)
            as expected_branch_sk
    from transfers
    inner join {{ ref('fct_activity') }} as fct on fct.advisor_id = transfers.advisor_id
)

select advisor_id, activity_id, 'credited to the wrong branch' as problem
from credited
where branch_sk <> expected_branch_sk

union all

select advisor_id, null, 'no activity on one side of the transfer'
from transfers
where (select count(distinct is_after) from credited where credited.advisor_id = transfers.advisor_id) < 2
