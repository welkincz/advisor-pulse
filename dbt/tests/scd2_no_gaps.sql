-- DQ020: no gaps between hire and termination. The first range starts on the hire date,
-- and each range ends where the next begins, unless a TERM event ended it (a rehire after
-- a TERM may start later). Returns one row per gap.
with ranges as (
    select
        advisor_id,
        valid_from,
        valid_to,
        lead(valid_from) over (partition by advisor_id order by valid_from) as next_from,
        row_number() over (partition by advisor_id order by valid_from) as n
    from {{ ref('int_advisor_history') }}
),

terms as (
    select advisor_id, effective_date
    from {{ ref('stg_advisor_assignment') }}
    where reason_code = 'TERM'
)

select ranges.advisor_id, ranges.valid_from, ranges.valid_to, ranges.next_from, 'gap' as problem
from ranges
left join terms
    on ranges.advisor_id = terms.advisor_id
    and ranges.valid_to = terms.effective_date
where ranges.next_from is not null
    and ranges.next_from <> ranges.valid_to
    and terms.advisor_id is null

union all

select ranges.advisor_id, ranges.valid_from, ranges.valid_to, null, 'starts after hire'
from ranges
inner join {{ ref('stg_advisor') }} as advisor on ranges.advisor_id = advisor.advisor_id
where ranges.n = 1 and ranges.valid_from <> advisor.hire_date
