-- Late-arriving fixture rows (defects.json LATE_ARRIVING) keep their original week and are
-- flagged; rows delivered on time are not flagged.
{{ config(enabled=target.name == 'ci') }}

with late as (
    select *
    from (
        values
        ('ACT-3e83f68f9ae3', '2026-W37'),
        ('ACT-abeb9873de2a', '2026-W37'),
        ('ACT-8f6bda71a42f', '2026-W38'),
        ('ACT-ec6171ef0cc0', '2026-W37'),
        ('ACT-f0fd2f1ddb01', '2026-W38'),
        ('ACT-605d22cf2d69', '2026-W38'),
        ('ACT-0bdaf000d60d', '2026-W39'),
        ('ACT-14ad2f7878c5', '2026-W39')
    ) as t (activity_id, original_week)
)

select late.activity_id, late.original_week, fct.iso_week_id, fct.is_late_arriving
from late
left join {{ ref('fct_activity') }} as fct using (activity_id)
where fct.iso_week_id is distinct from late.original_week or not fct.is_late_arriving

union all

select activity_id, null, iso_week_id, is_late_arriving
from {{ ref('fct_activity') }}
where is_late_arriving and activity_id not in (select activity_id from late)
