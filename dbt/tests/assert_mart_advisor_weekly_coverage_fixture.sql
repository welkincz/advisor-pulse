-- Hand-checked fixture advisor (PLAN.md §7 COVERAGE_13W): ADV-10002 in 2026-W40 has 13
-- active book clients at week end, 11 of them with a completed activity between
-- 2026-07-06 and 2026-10-04, so coverage is 11 / 13 = 0.8462.
{{ config(enabled=target.name == 'ci') }}

select iso_week_id, advisor_id, book_size, clients_covered_13w, coverage_rate_13w
from {{ ref('mart_advisor_weekly') }}
where advisor_id = 'ADV-10002'
    and iso_week_id = '2026-W40'
    and not (book_size = 13 and clients_covered_13w = 11 and coverage_rate_13w = 0.8462)

union all

select '2026-W40', 'ADV-10002', null, null, null
where not exists (
    select 1 from {{ ref('mart_advisor_weekly') }}
    where advisor_id = 'ADV-10002' and iso_week_id = '2026-W40'
)
