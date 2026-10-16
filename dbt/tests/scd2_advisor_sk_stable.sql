-- Checks fixture ground truth, so it runs only on the ci target (make dbt-build-ci).
{{ config(enabled=target.name == 'ci') }}
-- advisor_sk must not change across rebuilds: facts and exports key on it. These values
-- are pinned; if this fails, the key formula changed. ADV-10004 transfers on 2026-09-21,
-- so it has two ranges. Returns one row per expected key that is missing.
with expected as (
    select *
    from (
        values
        ('897eed8168a442bbccf551c7a336fa2e', 'ADV-10004', date '2017-09-11'),
        ('b88e22223b091b205ab928b1f06afcd8', 'ADV-10004', date '2026-09-21'),
        ('UNKNOWN', 'UNKNOWN', date '1900-01-01')
    ) as pinned (advisor_sk, advisor_id, valid_from)
)

select expected.*
from expected
left join {{ ref('dim_advisor') }} as dim
    on expected.advisor_sk = dim.advisor_sk
    and expected.advisor_id = dim.advisor_id
    and expected.valid_from = dim.valid_from
where dim.advisor_sk is null
