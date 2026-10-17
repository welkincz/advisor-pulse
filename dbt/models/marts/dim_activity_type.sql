-- Activity type dimension (PLAN.md §6.8): the four contract activity types and how the
-- KPIs treat them. counts_as_contact feeds CLIENTS_CONTACTED; is_appointment_like feeds
-- AVG_MEET_MIN (completed APPOINTMENT and REVIEW).
select *
from (
    values
    ('CALL_OUT', 'Outbound call', true, false),
    ('CALL_IN', 'Inbound call', true, false),
    ('APPOINTMENT', 'Appointment', true, true),
    ('REVIEW', 'Review', true, true)
) as activity_type (activity_type, label, counts_as_contact, is_appointment_like)
