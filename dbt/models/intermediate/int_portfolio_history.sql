-- SCD2 holder ranges from portfolio assignment events, built like int_advisor_history
-- (ADR 0001): each event opens a range that runs until the portfolio's next event, so a
-- portfolio has exactly one holder from its first event on. DQ024 checks the ranges.
with events as (
    select * from {{ ref('stg_portfolio_assignment') }}
    where effective_date is not null
),

-- Two events on one day for one portfolio: the later id wins, so no range is empty.
one_per_day as (
    select *
    from events
    qualify row_number() over (
        partition by portfolio_id, effective_date
        order by portfolio_assignment_id desc
    ) = 1
)

select
    one_per_day.portfolio_id,
    portfolio.branch_id as transit_branch_id,
    one_per_day.advisor_id,
    one_per_day.reason_code as change_reason,
    one_per_day.effective_date as valid_from,
    coalesce(
        lead(one_per_day.effective_date) over (
            partition by one_per_day.portfolio_id
            order by one_per_day.effective_date
        ),
        date '9999-12-31'
    ) as valid_to,
    one_per_day.portfolio_assignment_id
from one_per_day
-- An event for a portfolio missing from the master drops here; the relationships test on
-- stg_portfolio_assignment reports it.
inner join {{ ref('stg_portfolio') }} as portfolio using (portfolio_id)
