-- DQ014 (warn): more than 0.5% of the active book names a portfolio the master lacks.
-- Those clients still count, under the advisor fallback, so this warns and never fails.
{{ config(severity='warn') }}

select iso_week_id, rows_affected, rows_in_batch, rate
from {{ ref('mart_dq_weekly') }}
where rule_id = 'DQ014' and rate > 0.005
