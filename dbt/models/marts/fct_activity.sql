-- Activity fact (PLAN.md §6.8), one row per activity, credited to the advisor's branch as
-- of the activity date. Incremental delete+insert: each run rebuilds every activity dated
-- within the lookback (28 days by default) of the latest one already loaded, so rows that
-- arrive up to four weeks late land in their original week, and a full refresh gives the
-- same table.
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='activity_id',
    on_schema_change='fail',
) }}

with enriched as (
    select * from {{ ref('int_activity_enriched') }}
    {% if is_incremental() %}
    where activity_date >= (
        select max(activity_date) - {{ var('fct_activity_lookback_days', 28) }} from {{ this }}
    )
    {% endif %}
)

select
    activity_id,
    activity_date,
    iso_week_id,
    case
        when is_advisor_matched
            then md5(advisor_id || '|' || strftime(advisor_valid_from, '%Y-%m-%d'))
        else 'UNKNOWN'
    end as advisor_sk,
    advisor_id,
    md5(attributed_branch_id) as branch_sk,
    case when is_client_matched then md5(client_id) end as client_sk,
    fsa_code,
    activity_type,
    channel,
    status,
    outcome,
    product_line,
    duration_min,
    status = 'COMPLETED' as is_completed,
    activity_type = 'APPOINTMENT' as is_appointment,
    activity_type = 'APPOINTMENT'
        and status = 'COMPLETED'
        and coalesce(outcome in ('PLAN_CREATED', 'PRODUCT_OPENED'), false) as is_conversion,
    is_late_arriving,
    booked_from_activity_id,
    _batch_id
from enriched
