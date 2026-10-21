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
    -- Fiscal year starts 1 November: FY26 is 2025-11-01 to 2026-10-31.
    select 'fy_last_day', {{ fiscal_quarter_id("date '2025-10-31'") }}, 'FY25-Q4'
    union all
    select 'fy_first_day', {{ fiscal_quarter_id("date '2025-11-01'") }}, 'FY26-Q1'
    union all
    select 'fy_q2_start', {{ fiscal_quarter_id("date '2026-02-01'") }}, 'FY26-Q2'
    union all
    select 'fy_end', {{ fiscal_quarter_id("date '2026-10-31'") }}, 'FY26-Q4'
    union all
    select 'fy_month_november', cast({{ fiscal_month("date '2025-11-15'") }} as varchar), '1'
    union all
    select 'fy_quarter_start', cast({{ fiscal_quarter_start("date '2026-01-20'") }} as varchar), '2025-11-01'
    union all
    select 'fy_quarter_start_q4', cast({{ fiscal_quarter_start("date '2026-10-18'") }} as varchar), '2026-08-01'
    union all
    select 'iso_week_start_sunday',
        cast({{ iso_week_start("date '2026-10-04'") }} as varchar),
        '2026-09-28'
)

select * from cases where actual is distinct from expected
