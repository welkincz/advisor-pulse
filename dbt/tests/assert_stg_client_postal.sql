-- Checks fixture ground truth, so it runs only on the ci target (make dbt-build-ci).
{{ config(enabled=target.name == 'ci') }}
-- DQ011 on fixtures: every dirty postal code in fixtures/defects.json normalizes on
-- stg_client. expected_value is the `A1A 1A1` code, or `UNK` when the raw value is invalid.
-- Returns one row per failure. Runs from the repo root (`make dbt-build-ci`).
with defects as (
    select
        defect.natural_key as client_id,
        defect.raw_value,
        defect.expected_value,
        defect.detail
    from (
        select unnest(defects) as defect
        from read_json('fixtures/defects.json')
    )
    where defect.kind = 'DIRTY_POSTAL_CODE'
)

select
    defects.client_id,
    defects.raw_value,
    defects.expected_value,
    defects.detail,
    client.postal_code,
    client.fsa_code,
    client.postal_valid_flag
from defects
left join {{ ref('stg_client') }} as client on client.client_id = defects.client_id
where
    client.client_id is null
    or (
        defects.expected_value = 'UNK'
        and not (
            client.fsa_code = 'UNK'
            and client.postal_code is null
            and not client.postal_valid_flag
        )
    )
    or (
        defects.expected_value <> 'UNK'
        and not (
            client.postal_code = defects.expected_value
            and client.fsa_code = substr(defects.expected_value, 1, 3)
            and client.postal_valid_flag
        )
    )

union all

select
    null as client_id,
    null as raw_value,
    null as expected_value,
    'no DIRTY_POSTAL_CODE defects were read' as detail,
    null as postal_code,
    null as fsa_code,
    null as postal_valid_flag
where (select count(*) from defects) = 0
