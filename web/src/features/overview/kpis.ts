import type { KpiCode } from '../../data/generated/weekly_report'

/** The business definitions in PLAN.md §7, with operational rates kept separate. */
export const KPI_CODES: readonly KpiCode[] = [
  'PRTF_CONTACT_12M', 'ACT_PER_ADV', 'CALLS_OUT', 'APPT_BOOKED', 'CALL_TO_APPT', 'SHOW_RATE', 'APPT_CONV',
  'CLIENTS_CONTACTED', 'AVG_MEET_MIN', 'NO_SHOW_RATE', 'LATE_RATE', 'QUAR_RATE',
]

export const KPI_DEFINITIONS: Record<KpiCode, string> = {
  PRTF_CONTACT_12M: 'Active portfolio clients with at least one completed contact by any advisor in the trailing 12 months divided by active portfolio clients at week end.',
  ACT_PER_ADV: 'Completed activities divided by active advisors in the week. Active advisors exclude terminated advisors and branch managers.',
  CALLS_OUT: 'Completed outbound calls in the week.',
  APPT_BOOKED: 'Appointments created in the week.',
  CALL_TO_APPT: 'Appointments booked from a call in the week divided by completed outbound calls in the week.',
  SHOW_RATE: 'Held appointments divided by held plus no-show appointments scheduled in the week. Cancelled appointments are excluded.',
  APPT_CONV: 'Held appointments resulting in a plan or opened product divided by held appointments.',
  CLIENTS_CONTACTED: 'Distinct clients with at least one completed contact activity in the week.',
  AVG_MEET_MIN: 'Average minutes for completed appointments and reviews.',
  NO_SHOW_RATE: 'One minus the show rate.',
  LATE_RATE: 'Late-arriving rows divided by rows loaded in the batch.',
  QUAR_RATE: 'Quarantined rows divided by rows read in the batch.',
}

export const RATE_CODES = new Set<KpiCode>([
  'PRTF_CONTACT_12M', 'CALL_TO_APPT', 'SHOW_RATE', 'APPT_CONV', 'NO_SHOW_RATE', 'LATE_RATE', 'QUAR_RATE',
])

export const LOWER_IS_BETTER = new Set<KpiCode>(['NO_SHOW_RATE', 'LATE_RATE', 'QUAR_RATE'])
