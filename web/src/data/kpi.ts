import type { KpiCode } from './generated/manifest'

/** Display names, matching the narrative prompt's KPI_LABELS (src/pulse/narrative/prompt.py). */
export const KPI_LABELS: Record<KpiCode, string> = {
  ACT_PER_ADV: 'Activities per advisor',
  CALLS_OUT: 'Outbound calls',
  APPT_BOOKED: 'Appointments booked',
  CALL_TO_APPT: 'Call-to-appointment rate',
  SHOW_RATE: 'Show rate',
  APPT_CONV: 'Appointment conversion',
  CLIENTS_CONTACTED: 'Clients contacted',
  COVERAGE_13W: '13-week coverage',
  AVG_MEET_MIN: 'Average meeting minutes',
  NO_SHOW_RATE: 'No-show rate',
  LATE_RATE: 'Late-arriving rate',
  QUAR_RATE: 'Quarantine rate',
}

const RATES = new Set<KpiCode>(['CALL_TO_APPT', 'SHOW_RATE', 'APPT_CONV', 'COVERAGE_13W', 'NO_SHOW_RATE', 'LATE_RATE', 'QUAR_RATE'])
/** Averages keep one decimal even when whole, so a column of them lines up (16.0, not 16). */
const AVERAGES = new Set<KpiCode>(['ACT_PER_ADV', 'AVG_MEET_MIN'])

export function formatKpi(code: KpiCode, value: number | null | undefined): string {
  if (value === null || value === undefined) return '–'
  if (RATES.has(code)) return `${(value * 100).toFixed(1)}%`
  if (AVERAGES.has(code)) return value.toFixed(1)
  return Number.isInteger(value) ? value.toLocaleString('en-CA') : value.toFixed(1)
}

export function formatWow(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return 'no prior week'
  const sign = pct > 0 ? '+' : pct < 0 ? '−' : '±'
  return `${sign}${Math.abs(pct * 100).toFixed(1)}% WoW`
}
