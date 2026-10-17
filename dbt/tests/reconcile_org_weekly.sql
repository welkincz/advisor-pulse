-- DQ022 and DQ023 on mart_org_weekly: each additive measure on a national, region or
-- district row equals the sum over its children, every week; rates lie within [0, 1].
-- unique_clients_contacted is a distinct count and is not additive.
{{ reconcile_rollup(
    ref('mart_org_weekly'),
    leaf_where="level = 'BRANCH'",
    non_additive=['unique_clients_contacted'],
) }}
