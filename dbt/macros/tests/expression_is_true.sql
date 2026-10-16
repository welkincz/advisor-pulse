{#- Rows where the SQL expression is false (or null) fail the test. -#}
{% test expression_is_true(model, expression) %}
select *
from {{ model }}
where not coalesce(({{ expression }}), false)
{% endtest %}
