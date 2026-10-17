-- Proves reconcile_rollup catches a broken roll-up: one branch's calls_out is raised by 1
-- in the latest week and one district's coverage_rate_13w is set to 1.2. The check must
-- then report exactly the branch's district for DQ022 (its region still matches the
-- unchanged districts) and the altered district for DQ023. Returns a row for anything
-- missed or unexpected. It tests the macro, not the data, so it runs on the fixtures only
-- (enabled in reconcile_tests.yml, so the yml patch has a node on every target).

{% set altered %}
    select * replace (
        case
            when level = 'BRANCH' and node_id = (select min(node_id) from {{ ref('mart_org_weekly') }} where level = 'BRANCH')
                and iso_week_id = (select max(iso_week_id) from {{ ref('mart_org_weekly') }})
            then calls_out + 1 else calls_out
        end as calls_out,
        case
            when level = 'DISTRICT' and node_id = (select min(node_id) from {{ ref('mart_org_weekly') }} where level = 'DISTRICT')
                and iso_week_id = (select max(iso_week_id) from {{ ref('mart_org_weekly') }})
            then 1.2 else coverage_rate_13w
        end as coverage_rate_13w
    )
    from {{ ref('mart_org_weekly') }}
{% endset %}

with caught as (
    {{ reconcile_rollup(
        ref('mart_org_weekly'),
        leaf_where="level = 'BRANCH'",
        non_additive=['unique_clients_contacted'],
        from_sql=altered,
    ) }}
),

branch as (
    select node_id, parent_id as district_id, iso_week_id
    from {{ ref('mart_org_weekly') }}
    where level = 'BRANCH'
        and node_id = (select min(node_id) from {{ ref('mart_org_weekly') }} where level = 'BRANCH')
        and iso_week_id = (select max(iso_week_id) from {{ ref('mart_org_weekly') }})
),

expected as (
    select 'DQ022' as rule_id, 'calls_out' as measure, org.node_id
    from {{ ref('mart_org_weekly') }} as org, branch
    where org.iso_week_id = branch.iso_week_id
        and org.node_id = branch.district_id
    union all
    select 'DQ023', 'coverage_rate_13w', min(node_id)
    from {{ ref('mart_org_weekly') }}
    where level = 'DISTRICT'
    having count(*) > 0
),

actual as (
    select rule_id, measure, node_id from caught
)

(select *, 'missed' as problem from expected except select *, 'missed' from actual)
union all
(select *, 'unexpected' from actual except select *, 'unexpected' from expected)
