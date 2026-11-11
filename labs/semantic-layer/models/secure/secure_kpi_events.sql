-- ILLUSTRATION ONLY, not deployed permissions. A row-level filter in the style of BI
-- row-level security: the view returns only the KPI events in the org node that the
-- session's viewer may read. The viewer comes from a DuckDB session variable:
--     SET VARIABLE pulse_viewer = 'dm_gta';
-- An unset or unknown viewer matches no scope row, so the view returns nothing (fail
-- closed). DuckDB has no per-user grants here; anyone with the file can read the base
-- tables, which is why this is an illustration of the filter logic and nothing more.
select events.*
from {{ ref('sem_kpi_events') }} as events
inner join {{ ref('sem_org') }} as org using (branch_id)
inner join {{ ref('viewer_scope') }} as scope
    on scope.viewer_id = getvariable('pulse_viewer')
    and (
        scope.scope_level = 'NATIONAL'
        or (scope.scope_level = 'REGION' and scope.scope_value = org.region_code)
        or (scope.scope_level = 'DISTRICT' and scope.scope_value = org.district_code)
        or (scope.scope_level = 'BRANCH' and scope.scope_value = org.branch_id)
    )
