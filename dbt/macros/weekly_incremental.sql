{#- Weekly incremental models (#304). A weekly run recomputes only the weeks that a new
    extract can change and keeps the rest, instead of rebuilding two years of history.

    A model opts in with
        materialized='incremental', incremental_strategy='replace_from'
    and filters its weeks with `where iso_week_id >= {{ incremental_floor() }}` inside
    `{% if is_incremental() %}`. The strategy deletes every row from that floor on and
    inserts what the run produced, so a week that no longer has rows does not linger.
    The macro is called inside a conditional, so each model names what it reads with a
    `-- depends_on:` line (dim_date, and int_contact_window with reported_weeks_only).

    incremental_floor() is the first key the run rebuilds, the earlier of:
      * the latest week already in the model, less `weekly_lookback_weeks` (4 by default,
        the 28 days fct_activity uses). Rows arrive up to 3 weeks late and a booking counts
        in the week it was made, at most a week before the visit. A run that loads nothing
        new rebuilds the same weeks and gives the same table;
      * the earliest day that any raw row loaded since the model's last stamped build
        takes effect (activity, booking or schedule date, CLNT update, HR and portfolio
        assignment, advisor termination, a portfolio master's first assignment; a branch
        master row reaches all of history). So a past-range backfill or a row later than the lookback rebuilds
        from its own week. assert_late_rows_within_lookback warns when that happens;
    or '' (everything) when the model is empty, or when `reported_weeks_only` and its
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

        -- The runner stamps each incremental table after a build with the newest raw
        -- `_loaded_at` that build saw (pulse.runner.refresh). Rows loaded since then may
        -- touch any week: a past-range backfill, history extended earlier, a row later
        -- than the lookback. Without a stamp (plain `dbt build`) only the lookback applies.
        stamp as (
            select try_cast(json_extract_string(comment, '$.loaded_through') as timestamptz)
                as loaded_through
            from duckdb_tables()
            where database_name = current_database()
                and schema_name = '{{ this.schema }}'
                and table_name = '{{ this.identifier }}'
        ),

        new_rows as (
            select {{ toronto_date('least(' ~ '"ACTIVITY_TS", coalesce("CREATED_TS", "ACTIVITY_TS"), coalesce("SCHEDULED_TS", "ACTIVITY_TS"))') }} as day
            from raw.snowflake__activity
            where _loaded_at > (select loaded_through from stamp)
            union all
            select {{ toronto_date('"LAST_UPD_TS"') }}
            from raw.teradata__clnt
            where _loaded_at > (select loaded_through from stamp)
            union all
            select "EFF_DT" from raw.teradata__advsr_asgn
            where _loaded_at > (select loaded_through from stamp)
            union all
            select "EFF_DT" from raw.teradata__prtf_asgn
            where _loaded_at > (select loaded_through from stamp)
            union all
            -- Masters hold current state. A late termination counts from its date; a
            -- portfolio master row from its earliest assignment, which the inner join in
            -- int_portfolio_history dropped until now; a branch row (name, district,
            -- closure) applies to every week, so it rebuilds all of history.
            select least("TERM_DT", {{ toronto_date('"LAST_UPD_TS"') }})
            from raw.teradata__advsr
            where _loaded_at > (select loaded_through from stamp)
            union all
            select least(
                master."OPEN_DT",
                (select min(asgn."EFF_DT") from raw.teradata__prtf_asgn as asgn
                 where asgn."PRTF_ID" = master."PRTF_ID")
            )
            from raw.teradata__prtf as master
            where master._loaded_at > (select loaded_through from stamp)
            union all
            select date '1900-01-01' from raw.teradata__brnch
            where _loaded_at > (select loaded_through from stamp)
        ),

        floor_week as (
            select strftime(
                least(
                    min(dim_date.week_start) - {{ 7 * lookback }},
                    coalesce((select min(day) from new_rows), date '9999-12-31')
                ),
                '%G-W%V'
            ) as iso_week_id
            from {{ ref('dim_date') }} as dim_date
            inner join horizon on dim_date.iso_week_id = horizon.last_week
            having count(*) > 0
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
