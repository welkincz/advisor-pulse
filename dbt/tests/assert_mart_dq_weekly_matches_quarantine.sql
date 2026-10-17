-- mart_dq_weekly's quarantine counts reconcile with quarantine.rejected_rows: per rule, the
-- weekly rows add up to every rejected row, and the total matches the load manifest's
-- rows_quarantined. Returns each rule, or the total, that disagrees.
with mart as (
    select * from {{ ref('mart_dq_weekly') }} where action = 'QUARANTINE'
),

rejected as (
    select rule_id, count(*) as rejected_rows
    from {{ source('quarantine', 'rejected_rows') }}
    group by rule_id
)

select coalesce(mart_totals.rule_id, rejected.rule_id) as key, mart_totals.rows_affected, rejected.rejected_rows
from (select rule_id, sum(rows_affected) as rows_affected from mart group by rule_id) as mart_totals
full outer join rejected using (rule_id)
where mart_totals.rows_affected is distinct from coalesce(rejected.rejected_rows, 0)

union all

select 'total', (select sum(rows_affected) from mart),
    (select sum(rows_quarantined) from {{ source('meta', 'load_manifest') }}
     where status = 'LOADED' and table_name in ('activity', 'CLNT'))
where (select sum(rows_affected) from mart) is distinct from (
    select sum(rows_quarantined) from {{ source('meta', 'load_manifest') }}
    where status = 'LOADED' and table_name in ('activity', 'CLNT')
)
