import { KPI_LABELS, formatKpi } from '../../data'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { KPI_CODES } from './kpis'

/** A week at least this far back makes "the lowest since" worth saying. */
const NOTABLE_GAP = 8

export interface Headline { lead: string; support: string }

function moved(code: KpiCode, row: WeeklyReport): string {
  const pct = row.wow_pct
  if (pct == null) return `was ${formatKpi(code, row.value)}`
  if (Math.abs(pct) < 0.005) return `held steady at ${formatKpi(code, row.value)}`
  return `${pct > 0 ? 'rose' : 'fell'} ${Math.abs(pct * 100).toFixed(1)}% to ${formatKpi(code, row.value)}`
}

/** "the lowest since 2025-W52" when the week is the most extreme for a while, else ''. */
export function extremeSince(series: readonly WeeklyReport[], week: string): string {
  const at = series.findIndex((row) => row.iso_week_id === week)
  const row = series[at]
  if (!row || row.value == null || row.wow_pct == null || Math.abs(row.wow_pct) < 0.005) return ''
  const falling = row.wow_pct < 0
  for (let i = at - 1; i >= 0; i--) {
    const prior = series[i]!.value
    if (prior == null) continue
    if (falling ? prior <= row.value : prior >= row.value) {
      return at - i >= NOTABLE_GAP ? `the ${falling ? 'lowest' : 'highest'} since ${series[i]!.iso_week_id}` : ''
    }
  }
  return at >= NOTABLE_GAP ? `the ${falling ? 'lowest' : 'highest'} in ${at + 1} weeks on record` : ''
}

/**
 * The national headline for a week, written from the numbers: how the lead KPI moved and
 * whether that is unusual, then the biggest anomaly elsewhere. The narrative model writes
 * region and district summaries; the national line stays deterministic.
 */
export function weekHeadline(history: readonly WeeklyReport[], week: string, lead: KpiCode = 'ACT_PER_ADV'): Headline | null {
  const series = history.filter((row) => row.kpi_code === lead).sort((a, b) => a.iso_week_id.localeCompare(b.iso_week_id))
  const row = series.find((item) => item.iso_week_id === week)
  if (!row) return null
  const since = extremeSince(series, week)
  const leadText = `${KPI_LABELS[lead]} ${moved(lead, row)}${since ? `, ${since}` : ''}.`

  const others = history
    .filter((item) => item.iso_week_id === week && item.kpi_code !== lead && item.flag === 'ANOMALY' && item.wow_pct != null)
    .filter((item) => KPI_CODES.includes(item.kpi_code))
    .sort((a, b) => Math.abs(b.wow_pct!) - Math.abs(a.wow_pct!))
  const top = others[0]
  const support = top
    ? `${KPI_LABELS[top.kpi_code]} ${moved(top.kpi_code, top)}, outside its usual range${others.length > 1 ? `, one of ${others.length} measures flagged this week` : ''}.`
    : 'Every other measure stayed within its usual range.'
  return { lead: leadText, support }
}
