-- Grain is client_id × iso_week_id. Returns one row per duplicate.
select client_id, iso_week_id, count(*) as row_count
from {{ ref('int_client_book_weekly') }}
group by client_id, iso_week_id
having count(*) > 1
