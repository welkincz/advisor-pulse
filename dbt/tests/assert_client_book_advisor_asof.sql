-- Every book row's primary advisor has a dim_advisor range covering week_end
-- (activity_date >= valid_from and activity_date < valid_to, PLAN.md §6.8).
-- advisor_id alone is not enough: dim_advisor is SCD2.
select
    book.client_id,
    book.iso_week_id,
    book.week_end,
    book.primary_advisor_id,
    book.is_active
from {{ ref('int_client_book_weekly') }} as book
where not exists (
    select 1
    from {{ ref('dim_advisor') }} as advisor
    where advisor.advisor_id = book.primary_advisor_id
        and book.week_end >= advisor.valid_from
        and book.week_end < advisor.valid_to
)
