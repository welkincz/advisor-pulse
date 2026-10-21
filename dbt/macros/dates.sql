{#- Date conventions from PLAN.md §6: timestamps are UTC TIMESTAMPTZ, business dates are
    America/Toronto, weeks are ISO (Monday start) and labelled YYYY-Www. -#}

{% macro toronto_date(ts) -%}
    cast(timezone('America/Toronto', {{ ts }}) as date)
{%- endmacro %}

{% macro iso_week_id(day) -%}
    strftime({{ day }}, '%G-W%V')
{%- endmacro %}

{% macro iso_week_start(day) -%}
    cast(date_trunc('week', {{ day }}) as date)
{%- endmacro %}

{#- Fiscal calendar (PLAN.md §6): the year starts on 1 November, as at Canadian banks.
    FY26 runs 2025-11-01 to 2026-10-31; Q1 is Nov–Jan, Q2 Feb–Apr, Q3 May–Jul, Q4 Aug–Oct.
    A weekly figure belongs to the fiscal period that holds its week end (Sunday). -#}

{% macro fiscal_month(day) -%}
    cast(((month({{ day }}) + 1) % 12) + 1 as integer)
{%- endmacro %}

{% macro fiscal_year(day) -%}
    cast(year({{ day }}) + case when month({{ day }}) >= 11 then 1 else 0 end as integer)
{%- endmacro %}

{% macro fiscal_quarter(day) -%}
    cast((({{ fiscal_month(day) }} - 1) // 3) + 1 as integer)
{%- endmacro %}

{% macro fiscal_quarter_id(day) -%}
    format('FY{:02d}-Q{:d}', {{ fiscal_year(day) }} % 100, {{ fiscal_quarter(day) }})
{%- endmacro %}

{% macro fiscal_quarter_start(day) -%}
    cast(date_trunc('month', {{ day }}) - to_months(({{ fiscal_month(day) }} - 1) % 3) as date)
{%- endmacro %}
