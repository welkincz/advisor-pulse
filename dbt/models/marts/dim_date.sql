-- One row per calendar day. The range covers the 104-week history and the reporting
-- horizon; override with --vars '{dim_date_start: ..., dim_date_end: ...}'.
with days as (
    select cast(day as date) as date_day
    from range(
        date '{{ var("dim_date_start", "2024-01-01") }}',
        date '{{ var("dim_date_end", "2027-12-31") }}' + interval 1 day,
        interval 1 day
    ) as t(day)
)

select
    date_day,
    {{ iso_week_id('date_day') }} as iso_week_id,
    {{ iso_week_start('date_day') }} as week_start,
    cast({{ iso_week_start('date_day') }} + interval 6 day as date) as week_end,
    cast(isoyear(date_day) as integer) as iso_year,
    cast(week(date_day) as integer) as iso_week,
    cast(month(date_day) as integer) as month,
    cast(quarter(date_day) as integer) as quarter,
    cast(isodow(date_day) as integer) as day_of_week,
    isodow(date_day) >= 6 as is_weekend
from days
