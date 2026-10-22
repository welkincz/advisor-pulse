import type { KpiCode } from './generated/manifest'

/** Display names, matching the narrative prompt's KPI_LABELS (src/pulse/narrative/prompt.py). */
export const KPI_LABELS: Record<KpiCode, string> = {
  PRTF_CONTACT_12M: 'Portfolio contacted (12 months)',
  ACT_PER_ADV: 'Activities per advisor',
  CALLS_OUT: 'Outbound calls',
  APPT_BOOKED: 'Appointments booked',
  CALL_TO_APPT: 'Call-to-appointment rate',
  SHOW_RATE: 'Show rate',
  APPT_CONV: 'Appointment conversion',
  CLIENTS_CONTACTED: 'Clients contacted',
  AVG_MEET_MIN: 'Average meeting minutes',
  NO_SHOW_RATE: 'No-show rate',
  LATE_RATE: 'Late-arriving rate',
  QUAR_RATE: 'Quarantine rate',
}

/**
 * The lead KPI, portfolio contacted (12 months). A report without 12 months of history has
 * no value for it yet, so activities per advisor leads until it does (as the narrative does).
 */
export const LEAD_KPI: KpiCode = 'PRTF_CONTACT_12M'
export const FALLBACK_LEAD: KpiCode = 'ACT_PER_ADV'

type KpiValue = { kpi_code: KpiCode; value?: number | null; iso_week_id?: string }

/** The default measure for a page: the lead KPI when the latest summary has a value for it. */
export function defaultLead(summary: readonly KpiValue[]): KpiCode {
  return summary.some((row) => row.kpi_code === LEAD_KPI && row.value != null) ? LEAD_KPI : FALLBACK_LEAD
}

/** The KPI a week's headline leads with: the lead KPI if that week has a value for it. */
export function leadFor(history: readonly KpiValue[], week: string): KpiCode {
  return history.some((row) => row.kpi_code === LEAD_KPI && row.iso_week_id === week && row.value != null) ? LEAD_KPI : FALLBACK_LEAD
}

export const RATES: ReadonlySet<KpiCode> = new Set<KpiCode>(['PRTF_CONTACT_12M', 'CALL_TO_APPT', 'SHOW_RATE', 'APPT_CONV', 'NO_SHOW_RATE', 'LATE_RATE', 'QUAR_RATE'])
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
