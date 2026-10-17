import type { AdvisorWeekly } from '../../data/generated/advisor_weekly'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { LOWER_IS_BETTER } from '../overview/kpis'

/** One child in the ranking. `rank` is null when the KPI has no value that week. */
export interface LeaderRow {
  id: string
  name: string
  value: number | null
  rank: number | null
  priorRank: number | null
  trend: (number | null)[]
}

/** KPIs that exist below the national level; LATE_RATE and QUAR_RATE are batch-wide. */
export const ORG_KPIS: readonly KpiCode[] = [
  'ACT_PER_ADV', 'CALLS_OUT', 'APPT_BOOKED', 'CALL_TO_APPT', 'SHOW_RATE', 'APPT_CONV',
  'CLIENTS_CONTACTED', 'COVERAGE_13W', 'AVG_MEET_MIN', 'NO_SHOW_RATE',
]

function ratio(numerator: number, denominator: number): number | null {
  return denominator ? Math.round((numerator / denominator) * 10000) / 10000 : null
}

/** advisor_weekly has no appointments-booked-from-call count, so CALL_TO_APPT is absent. */
const ADVISOR_VALUE: Partial<Record<KpiCode, (row: AdvisorWeekly) => number | null>> = {
  ACT_PER_ADV: (r) => r.activities_completed,
  CALLS_OUT: (r) => r.calls_out,
  APPT_BOOKED: (r) => r.appointments_booked,
  SHOW_RATE: (r) => ratio(r.appointments_held, r.appointments_held + r.no_shows),
  APPT_CONV: (r) => ratio(r.conversions, r.appointments_held),
  CLIENTS_CONTACTED: (r) => r.unique_clients_contacted,
  COVERAGE_13W: (r) => r.coverage_rate_13w ?? null,
  AVG_MEET_MIN: (r) => r.avg_meeting_duration_min ?? null,
  NO_SHOW_RATE: (r) => {
    const show = ratio(r.appointments_held, r.appointments_held + r.no_shows)
    return show === null ? null : Math.round((1 - show) * 10000) / 10000
  },
}

export const ADVISOR_KPIS: readonly KpiCode[] = ORG_KPIS.filter((code) => code in ADVISOR_VALUE)

/** One advisor's value for a KPI, with the mart_org_weekly formula; null if it has none. */
export function advisorValue(code: KpiCode, row: AdvisorWeekly): number | null {
  return ADVISOR_VALUE[code]?.(row) ?? null
}

/** Dense rank, best first in the KPI's direction (as mart_weekly_report ranks). */
export function denseRank(values: ReadonlyMap<string, number | null>, code: KpiCode): Map<string, number> {
  const sign = LOWER_IS_BETTER.has(code) ? 1 : -1
  const distinct = [...new Set([...values.values()].filter((v): v is number => v !== null))].sort((a, b) => sign * (a - b))
  const position = new Map(distinct.map((value, index) => [value, index + 1]))
  const ranks = new Map<string, number>()
  for (const [id, value] of values) if (value !== null) ranks.set(id, position.get(value)!)
  return ranks
}

function sorted(rows: LeaderRow[]): LeaderRow[] {
  return rows.sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity) || a.name.localeCompare(b.name))
}

/** Children of one org node from weekly_report: ranks come from the mart. */
export function orgRows(history: readonly WeeklyReport[], code: KpiCode, weeks: readonly string[]): LeaderRow[] {
  const week = weeks.at(-1)
  const prior = weeks.at(-2)
  const byNode = new Map<string, Map<string, WeeklyReport>>()
  for (const row of history) {
    if (row.kpi_code !== code) continue
    if (!byNode.has(row.node_id)) byNode.set(row.node_id, new Map())
    byNode.get(row.node_id)!.set(row.iso_week_id, row)
  }
  const rows: LeaderRow[] = []
  for (const [id, byWeek] of byNode) {
    const current = week ? byWeek.get(week) : undefined
    if (!current) continue
    rows.push({
      id,
      name: current.node_name,
      value: current.value ?? null,
      rank: current.rank_in_parent ?? null,
      priorRank: (prior ? byWeek.get(prior)?.rank_in_parent : undefined) ?? null,
      trend: weeks.map((w) => byWeek.get(w)?.value ?? null),
    })
  }
  return sorted(rows)
}

/** Advisors in one branch from advisor_weekly, ranked here with the mart's direction. */
export function advisorRows(history: readonly AdvisorWeekly[], code: KpiCode, weeks: readonly string[]): LeaderRow[] {
  const value = ADVISOR_VALUE[code]
  if (!value) return []
  const week = weeks.at(-1)
  const prior = weeks.at(-2)
  const byWeek = new Map<string, Map<string, number | null>>(weeks.map((w) => [w, new Map()]))
  for (const row of history) byWeek.get(row.iso_week_id)?.set(row.advisor_id, value(row))
  const current = (week && byWeek.get(week)) || new Map<string, number | null>()
  const ranks = denseRank(current, code)
  const priorRanks = prior ? denseRank(byWeek.get(prior)!, code) : new Map<string, number>()
  return sorted([...current.keys()].map((id) => ({
    id,
    name: id,
    value: current.get(id) ?? null,
    rank: ranks.get(id) ?? null,
    priorRank: priorRanks.get(id) ?? null,
    trend: weeks.map((w) => byWeek.get(w)!.get(id) ?? null),
  })))
}

/** Places moved since the prior week: positive is up the table. */
export function rankChange(row: LeaderRow): number | null {
  return row.rank !== null && row.priorRank !== null ? row.priorRank - row.rank : null
}
