{#- Weekly incremental models (#304). A weekly run recomputes only the weeks that a new
    extract can change and keeps the rest, instead of rebuilding two years of history.

    A model opts in with
        materialized='incremental', incremental_strategy='replace_from'
    and filters its weeks with `where iso_week_id >= {{ incremental_floor() }}` inside
    `{% if is_incremental() %}`. The strategy deletes every row from that floor on and
    inserts what the run produced, so a week that no longer has rows does not linger.
    The macro is called inside a conditional, so each model names what it reads with a
    `-- depends_on:` line (dim_date, and int_contact_window with reported_weeks_only).

    incremental_floor() is the first key the run rebuilds:
      * the latest week already in the model, less `weekly_lookback_weeks` (4 by default,
        the 28 days fct_activity uses). Rows arrive up to 3 weeks late, a booking counts
        in the week it was made (at most a week before the visit), and client, portfolio
        and HR changes take effect on their own date, so no source change reaches further
        back. A run that loads nothing new rebuilds the same weeks and gives the same table;
      * '' (everything) when the model is empty, or when `reported_weeks_only` and its
        first week is no longer reported: a history without the warm-up year starts its
        report later once it reaches a full year (int_contact_window).
    Config `replace_key` names the key (default iso_week_id); with fiscal_quarter_id the
    floor is the quarter that holds the floor week, and the model's weeks are read from
    first_week and last_week.

    tests/dbt/test_weekly_incremental.py proves an incremental run equals a full refresh. -#}

{% macro incremental_floor() -%}
    {%- set key = config.get('replace_key', 'iso_week_id') -%}
    {%- set quarterly = key == 'fiscal_quarter_id' -%}
    {%- set first_col = 'first_week' if quarterly else key -%}
    {%- set last_col = 'last_week' if quarterly else key -%}
    {%- set lookback = var('weekly_lookback_weeks', 4) | int -%}
    {%- set query -%}
        with horizon as (
            select min({{ first_col }}) as first_week, max({{ last_col }}) as last_week
            from {{ this }}
        ),

        floor_week as (
            select strftime(min(dim_date.week_start) - {{ 7 * lookback }}, '%G-W%V') as iso_week_id
            from {{ ref('dim_date') }} as dim_date
            inner join horizon on dim_date.iso_week_id = horizon.last_week
        )

        select
            {%- if config.get('reported_weeks_only', false) %}
            case when (select first_week from horizon) < (
                select min(iso_week_id) from {{ ref('int_contact_window') }} where is_reported
            ) then '' else
            {%- endif %}
            {%- if quarterly %}
            coalesce((
                select min(dim_date.week_fiscal_quarter_id)
                from {{ ref('dim_date') }} as dim_date
                inner join floor_week using (iso_week_id)
            ), '')
            {%- else %}
            coalesce((select iso_week_id from floor_week), '')
            {%- endif %}
            {%- if config.get('reported_weeks_only', false) %} end{% endif %}
    {%- endset -%}
    {#- A literal, so DuckDB prunes by it while scanning: the same value in the model's
        filter and in the strategy's delete, which runs before anything changes. -#}
    {%- if execute -%}
        {{ return("'" ~ run_query(query).columns[0].values()[0] ~ "'") }}
    {%- else -%}
        {{ return("''") }}
    {%- endif -%}
{%- endmacro %}

{% macro get_incremental_replace_from_sql(arg_dict) -%}
    {%- set target = arg_dict['target_relation'] -%}
    {%- set source = arg_dict['temp_relation'] -%}
    {%- set key = config.get('replace_key', 'iso_week_id') -%}
    {%- set columns = get_quoted_csv(arg_dict['dest_columns'] | map(attribute='name')) -%}
    delete from {{ target }} where {{ key }} >= {{ incremental_floor() }};

    insert into {{ target }} ({{ columns }})
    select {{ columns }} from {{ source }}
{%- endmacro %}
