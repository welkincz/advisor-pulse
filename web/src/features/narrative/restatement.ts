import { formatKpi, formatWow, type PulseData } from '../../data'
import type { NarrativeFact, NodeNarrative } from '../../data/generated/narrative'
import type { WeeklyReport } from '../../data/generated/weekly_report'

export const FIELDS = ['value', 'prior_week_value', 'wow_pct', 'rank_in_parent'] as const
export function figures(f: Pick<NarrativeFact, 'kpi_code' | typeof FIELDS[number]>) {
  return [formatKpi(f.kpi_code, f.value), formatKpi(f.kpi_code, f.prior_week_value), formatWow(f.wow_pct), String(f.rank_in_parent ?? '–')]
}
export function cited(n: NodeNarrative) {
  const ids = new Set([...n.bullets, ...(n.watchlist ?? [])].flatMap((b) => b.fact_ids))
  return n.facts_used.filter((f) => ids.has(f.fact_id))
}
export async function currentFacts(data: PulseData, n: NodeNarrative): Promise<Map<string, WeeklyReport>> {
  const groups = new Map<string, Set<string>>()
  for (const f of cited(n)) groups.set(f.node_id, (groups.get(f.node_id) ?? new Set()).add(f.iso_week_id))
  const rows = (await Promise.all([...groups].map(([node, weeks]) => data.weeklyReportHistory(node, [...weeks].sort())))).flat()
  return new Map(cited(n).map((f) => {
    const row = rows.find((r) => r.node_id === f.node_id && r.iso_week_id === f.iso_week_id && r.kpi_code === f.kpi_code)
    if (!row) throw new Error(`Current cited fact unavailable: ${f.fact_id}`)
    return [f.fact_id, row]
  }))
}
