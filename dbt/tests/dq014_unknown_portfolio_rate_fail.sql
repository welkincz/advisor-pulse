-- DQ014 (fail): more than 2% of the active book names a portfolio the master lacks. That
-- is no longer a few bad rows but a mapping failure (a portfolio master that didn't load,
-- a renumbering upstream), and publishing would quietly move whole books to the fallback
-- owner, so the run stops (PLAN.md §8). The 0.5% warning is dq014_unknown_portfolio_rate.
{{ config(severity='error') }}

select iso_week_id, rows_affected, rows_in_batch, rate
from {{ ref('mart_dq_weekly') }}
where rule_id = 'DQ014' and rate > 0.02
