-- DQ014 (warn): more than 0.5% of the active book names a portfolio the master lacks.
-- Those clients still count, under the advisor fallback, so this warns; above 2% the
-- companion test dq014_unknown_portfolio_rate_fail stops the run (PLAN.md §8).
{{ config(severity='warn') }}

select iso_week_id, rows_affected, rows_in_batch, rate
from {{ ref('mart_dq_weekly') }}
where rule_id = 'DQ014' and rate > 0.005
