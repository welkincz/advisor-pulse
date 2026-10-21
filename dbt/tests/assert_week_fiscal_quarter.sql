-- A week counts in the fiscal quarter holding its Sunday: 2025-W44 (Mon 27 Oct to Sun 2 Nov
-- 2025) is FY26-Q1, and every day of one ISO week maps to the same quarter.
with cases as (
    select 'w44_2025' as name, max(week_fiscal_quarter_id) as actual, 'FY26-Q1' as expected
    from {{ ref('dim_date') }} where iso_week_id = '2025-W44'
    union all
    select 'w43_2025', max(week_fiscal_quarter_id), 'FY25-Q4'
    from {{ ref('dim_date') }} where iso_week_id = '2025-W43'
    union all
    select 'one_quarter_per_week',
        cast(max(n) as varchar), '1'
    from (
        select iso_week_id, count(distinct week_fiscal_quarter_id) as n
        from {{ ref('dim_date') }} group by iso_week_id
    )
)
select * from cases where actual is distinct from expected
