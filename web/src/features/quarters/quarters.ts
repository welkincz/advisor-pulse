import type { OrgQuarterly } from '../../data/generated/org_quarterly'
import type { KpiCode } from '../../data/generated/weekly_report'
import { quarterBefore, yearEarlier } from '../../data/fiscal'

/**
 * How a measure reads over a fiscal quarter, so a quarter to date compares fairly with a
 * closed one:
 * - `rate`: a ratio rebuilt from the quarter's parts (show rate, activities per advisor).
 * - `weekly`: a flow, shown as its weekly average over the weeks reported.
 * - `quarter`: distinct clients over the quarter. It only grows as weeks are added, so it
 *   is compared once the quarter is complete.
 */
export type Basis = 'rate' | 'weekly' | 'quarter'

interface Measure { basis: Basis; value: (row: OrgQuarterly) => number | null }

const ratio = (num: number, den: number) => (den > 0 ? num / den : null)

export const QUARTER_MEASURES: Partial<Record<KpiCode, Measure>> = {
  ACT_PER_ADV: { basis: 'rate', value: (r) => r.activities_per_advisor ?? null },
  CALLS_OUT: { basis: 'weekly', value: (r) => r.calls_out / r.weeks_reported },
  APPT_BOOKED: { basis: 'weekly', value: (r) => r.appointments_booked / r.weeks_reported },
  CALL_TO_APPT: { basis: 'rate', value: (r) => r.call_to_appt_rate ?? null },
  SHOW_RATE: { basis: 'rate', value: (r) => r.show_rate ?? null },
  APPT_CONV: { basis: 'rate', value: (r) => r.conversion_rate ?? null },
  CLIENTS_CONTACTED: { basis: 'quarter', value: (r) => r.unique_clients_contacted },
  COVERAGE_13W: { basis: 'rate', value: (r) => r.coverage_rate_13w ?? null },
  AVG_MEET_MIN: { basis: 'rate', value: (r) => r.avg_meeting_duration_min ?? null },
  NO_SHOW_RATE: { basis: 'rate', value: (r) => ratio(r.no_shows, r.appointments_held + r.no_shows) },
}

export interface QuarterPoint {
  id: string
  value: number | null
  complete: boolean
  weeksReported: number
  weeksInQuarter: number
  start: string
  end: string
}

/** One node's quarters for a measure, oldest first; empty when the measure has no quarterly form. */
export function quarterSeries(rows: readonly OrgQuarterly[], nodeId: string, code: KpiCode): QuarterPoint[] {
  const measure = QUARTER_MEASURES[code]
  if (!measure) return []
  return rows.filter((r) => r.node_id === nodeId)
    .sort((a, b) => a.fiscal_quarter_id.localeCompare(b.fiscal_quarter_id))
    .map((r) => ({
      id: r.fiscal_quarter_id, value: measure.value(r), complete: r.is_complete, weeksReported: r.weeks_reported,
      weeksInQuarter: r.weeks_in_quarter, start: r.quarter_start, end: r.quarter_end,
    }))
}

export type Change = { value: number } | { value: null; reason: 'no-quarter' | 'to-date' }

/**
 * Relative change from the comparison quarter (`qoq`: the quarter before; `yoy`: the same
 * quarter a fiscal year earlier). Distinct clients wait until both quarters are complete.
 */
export function change(series: readonly QuarterPoint[], id: string, code: KpiCode, against: 'qoq' | 'yoy'): Change {
  const current = series.find((p) => p.id === id)
  const prior = series.find((p) => p.id === (against === 'qoq' ? quarterBefore(id) : yearEarlier(id)))
  if (!current || !prior || current.value === null || prior.value === null || prior.value === 0) return { value: null, reason: 'no-quarter' }
  if (QUARTER_MEASURES[code]?.basis === 'quarter' && (!current.complete || !prior.complete)) return { value: null, reason: 'to-date' }
  return { value: current.value / prior.value - 1 }
}

/** '9 of 13 weeks' for a quarter to date; null for a complete quarter. */
export function toDate(point: QuarterPoint): string | null {
  return point.complete ? null : `${point.weeksReported} of ${point.weeksInQuarter} weeks`
}
