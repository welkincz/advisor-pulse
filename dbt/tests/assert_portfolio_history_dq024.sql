-- DQ024 (error): portfolio holder ranges are a clean SCD2. Returns one row per problem:
-- a range that starts before its portfolio opened, a first range that starts after it,
-- consecutive ranges that overlap or leave a gap, or a holder who on the range's first
-- day is not employed or is a branch manager (who own no book).
with ranges as (
    select
        h.*,
        p.open_date,
        lag(h.valid_to) over (partition by h.portfolio_id order by h.valid_from) as prior_to,
        row_number() over (partition by h.portfolio_id order by h.valid_from) as n
    from {{ ref('int_portfolio_history') }} as h
    inner join {{ ref('stg_portfolio') }} as p using (portfolio_id)
)

select portfolio_id, valid_from, 'starts before the portfolio opened' as problem
from ranges where valid_from < open_date
union all
select portfolio_id, valid_from, 'first holder starts after the portfolio opened'
from ranges where n = 1 and valid_from > open_date
union all
select portfolio_id, valid_from, 'overlaps or leaves a gap after the prior range'
from ranges where n > 1 and prior_to <> valid_from
union all
select r.portfolio_id, r.valid_from, 'holder not an employed book owner on that day'
from ranges as r
where not exists (
    select 1
    from {{ ref('int_advisor_history') }} as a
    where a.advisor_id = r.advisor_id
        and r.valid_from >= a.valid_from
        and r.valid_from < a.valid_to
        and a.role_code <> 'BR_MGR'
)
