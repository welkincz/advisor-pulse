-- DQ020: exactly one current row per active advisor and none per terminated advisor,
-- whose last range ends on the termination date. Returns one row per bad advisor.
with history as (
    select
        advisor_id,
        count(*) filter (where valid_to = date '9999-12-31') as current_rows,
        max(valid_to) as last_valid_to
    from {{ ref('int_advisor_history') }}
    group by advisor_id
)

select advisor.advisor_id, advisor.term_date, history.current_rows, history.last_valid_to
from {{ ref('stg_advisor') }} as advisor
left join history on advisor.advisor_id = history.advisor_id
where
    (advisor.term_date is null and coalesce(history.current_rows, 0) <> 1)
    or (
        advisor.term_date is not null
        and (history.current_rows <> 0 or history.last_valid_to <> advisor.term_date)
    )
