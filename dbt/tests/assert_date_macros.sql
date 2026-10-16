-- Pins the date macros on the edge cases PLAN.md §6 cares about. Returns a row per failure.
with cases as (
    -- 02:00 UTC on 2 Oct is still 1 Oct in Toronto (EDT, UTC-4).
    select 'toronto_edt' as name,
        cast({{ toronto_date("timestamptz '2026-10-02 02:00:00+00'") }} as varchar) as actual,
        '2026-10-01' as expected
    union all
    -- 04:30 UTC on 15 Jan is 23:30 on 14 Jan in Toronto (EST, UTC-5).
    select 'toronto_est',
        cast({{ toronto_date("timestamptz '2026-01-15 04:30:00+00'") }} as varchar),
        '2026-01-14'
    union all
    -- ISO year differs from the calendar year at both ends.
    select 'iso_week_year_end', {{ iso_week_id("date '2027-01-03'") }}, '2026-W53'
    union all
    select 'iso_week_year_start', {{ iso_week_id("date '2024-12-30'") }}, '2025-W01'
    union all
    select 'iso_week_start_sunday',
        cast({{ iso_week_start("date '2026-10-04'") }} as varchar),
        '2026-09-28'
)

select * from cases where actual is distinct from expected
