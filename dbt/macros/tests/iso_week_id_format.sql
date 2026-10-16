{#- Every non-null value looks like 2026-W40 (week 01–53). -#}
{% test iso_week_id_format(model, column_name) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and not regexp_full_match({{ column_name }}, '[0-9]{4}-W(0[1-9]|[1-4][0-9]|5[0-3])')
{% endtest %}
