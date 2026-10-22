{#- Roll-up reconciliation (PLAN.md §8 DQ022 and DQ023), used by dbt/tests/reconcile_*.sql.

    reconcile_rollup returns one row per failure in a hierarchy table with a node column, a
    parent column and a grain (the week):
      - DQ022: on every row that is not a leaf (`leaf_where`), each additive measure equals
        the sum over its children; a non-leaf with no children compares against 0. The
        additive measures are all integer columns except `non_additive` (distinct counts),
        read from the relation when the test compiles, so a new count column is checked
        without editing the test.
      - DQ023: every column named with `_rate` (show_rate, portfolio_contacted_rate_12m, ...) is
        null or within [0, 1].
    `from_sql` replaces the relation's rows (same columns), so a test can feed it altered
    data and prove that a mismatch is caught. -#}

{% macro reconcile_rollup(relation, leaf_where, non_additive=[], grain=['iso_week_id'], node='node_id', parent='parent_id', from_sql=none) %}
    {%- set measures = [] -%}
    {%- set rates = [] -%}
    {%- if execute -%}
        {%- for column in adapter.get_columns_in_relation(relation) -%}
            {%- set name = column.name | lower -%}
            {%- if column.is_integer() and name not in non_additive -%}
                {%- do measures.append(name) -%}
            {%- elif '_rate' in name -%}
                {%- do rates.append(name) -%}
            {%- endif -%}
        {%- endfor -%}
        {%- if not measures -%}
            {{ exceptions.raise_compiler_error('reconcile_rollup found no additive measures in ' ~ relation) }}
        {%- endif -%}
    {%- endif -%}
    {%- set checks = [] -%}
    {%- for m in measures -%}
        {%- do checks.append(
            "select 'DQ022' as rule_id, '" ~ m ~ "' as measure, " ~ grain | join(', ') ~ ", node_id, "
            ~ "cast(" ~ m ~ " as double) as observed, cast(sum_" ~ m ~ " as double) as expected "
            ~ "from compared where " ~ m ~ " is distinct from sum_" ~ m
        ) -%}
    {%- endfor -%}
    {%- for r in rates -%}
        {%- do checks.append(
            "select 'DQ023', '" ~ r ~ "', " ~ grain | join(', ') ~ ", " ~ node ~ ", "
            ~ r ~ ", null from rows where " ~ r ~ " < 0 or " ~ r ~ " > 1"
        ) -%}
    {%- endfor -%}

    with rows as (
        {% if from_sql %}{{ from_sql }}{% else %}select * from {{ relation }}{% endif %}
    ),

    children as (
        select
            {{ grain | join(', ') }},
            {{ parent }} as parent_node
            {%- for m in measures %},
            sum({{ m }}) as sum_{{ m }}
            {%- endfor %}
        from rows
        where {{ parent }} is not null
        group by {{ grain | join(', ') }}, {{ parent }}
    ),

    compared as (
        select
            {% for g in grain %}rows.{{ g }}, {% endfor %}
            rows.{{ node }} as node_id
            {%- for m in measures %},
            rows.{{ m }},
            coalesce(children.sum_{{ m }}, 0) as sum_{{ m }}
            {%- endfor %}
        from rows
        left join children
            on {% for g in grain %}children.{{ g }} = rows.{{ g }} and {% endfor %}children.parent_node = rows.{{ node }}
        where not ({{ leaf_where }})
    )

    {{ checks | join('\n    union all\n    ') }}
{% endmacro %}
