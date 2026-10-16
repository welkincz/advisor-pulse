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
