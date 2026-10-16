-- DQ020: no two ranges of one advisor overlap. Returns each overlapping pair.
select a.advisor_id, a.valid_from, a.valid_to, b.valid_from as other_from, b.valid_to as other_to
from {{ ref('int_advisor_history') }} as a
inner join {{ ref('int_advisor_history') }} as b
    on a.advisor_id = b.advisor_id
    and a.valid_from < b.valid_from
    and b.valid_from < a.valid_to
