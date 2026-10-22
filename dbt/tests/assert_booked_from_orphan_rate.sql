-- Appointments booked on a call that is not in staging. The call is usually one ingest
-- quarantined (a null id, an invalid enum, a duration out of range), so a share about the
-- size of the quarantine rate is expected and the appointment is kept. A plain relationships
-- test warned on every run for that reason, and a warning that never clears gets ignored.
-- This one warns only when the share is several times the quarantine rate, and only once
-- there are enough bookings to judge (a first week's few dozen swing past 2% on one row):
-- then calls are going missing for some other reason.
{{ config(severity='warn') }}

with booked as (
    select
        a.activity_id,
        exists (
            select 1 from {{ ref('stg_activity') }} as call
            where call.activity_id = a.booked_from_activity_id
        ) as call_found
    from {{ ref('stg_activity') }} as a
    where a.booked_from_activity_id is not null
)

select
    count(*) as booked_from_call,
    count(*) filter (where not call_found) as call_missing,
    count(*) filter (where not call_found) / count(*) as missing_share
from booked
having count(*) >= 500
    and count(*) filter (where not call_found) > 0.02 * count(*)
