import { FALLBACK_LEAD, KPI_LABELS, formatKpi, leadFor } from '../../data'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { KPI_CODES } from './kpis'

/** A week at least this far back makes "the lowest since" worth saying. */
const NOTABLE_GAP = 8

/**
 * `lead` is the whole sentence. The overview splits it: `title` (how the lead KPI moved) is the
 * page title, short enough for two lines on a phone, and `record` ("The lowest since …", or '')
 * opens the line under it.
 */
export interface Headline { lead: string; title: string; record: string; support: string }

function moved(code: KpiCode, value: number | null | undefined, pct: number | null | undefined): string {
  if (pct == null) return `was ${formatKpi(code, value)}`
  if (Math.abs(pct) < 0.005) return `held steady at ${formatKpi(code, value)}`
  return `${pct > 0 ? 'rose' : 'fell'} ${Math.abs(pct * 100).toFixed(1)}% to ${formatKpi(code, value)}`
}

/**
 * How one measure moved, as the sentence the overview and every drill page open with:
 * "Portfolio contacted (12 months) held steady at 84.2%." Null when there is no value to report.
 * `label` names the measure where the page reads it differently (one advisor's activities).
 */
export function moveSentence(code: KpiCode, value: number | null | undefined, wow: number | null | undefined, label: string = KPI_LABELS[code]): string | null {
  return value == null ? null : `${label} ${moved(code, value, wow)}.`
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
  if (!row || row.value == null) return null
  const since = extremeSince(series, week)
  const title = moveSentence(lead, row.value, row.wow_pct)!
  const leadText = since ? `${title.slice(0, -1)}, ${since}.` : title
  const record = since ? `${since[0]!.toUpperCase()}${since.slice(1)}.` : ''

  const others = history
    .filter((item) => item.iso_week_id === week && item.kpi_code !== lead && item.flag === 'ANOMALY' && item.wow_pct != null)
    .filter((item) => KPI_CODES.includes(item.kpi_code))
    .sort((a, b) => Math.abs(b.wow_pct!) - Math.abs(a.wow_pct!))
  const top = others[0]
  const support = top
    ? `${KPI_LABELS[top.kpi_code]} ${moved(top.kpi_code, top.value, top.wow_pct)}, outside its usual range${others.length > 1 ? `, one of ${others.length} measures flagged this week` : ''}.`
    : 'Every other measure stayed within its usual range.'
  return { lead: leadText, title, record, support }
}

/**
 * The headline a page opens with for one node's history: led by `lead` (the page's lead KPI),
 * or by that week's own lead when `lead` has no value that week (a week without 12 months of
 * history leads with activities per advisor). The overview and the drill pages both use it.
 */
export function nodeHeadline(history: readonly WeeklyReport[], week: string, lead: KpiCode): Headline | null {
  return weekHeadline(history, week, lead) ?? weekHeadline(history, week, leadFor(history, week))
}

/** One measure's value this week and its change on the prior week, as a tile shows it. */
export interface Measure { code: KpiCode; value: number | null; wow: number | null }

/**
 * The opening sentence where only this week's tiles are at hand (one advisor): about `lead`,
 * or about activities when `lead` has no value yet. Null when neither has one.
 */
export function measuresSentence(measures: readonly Measure[], lead: KpiCode, label: (code: KpiCode) => string = (code) => KPI_LABELS[code]): string | null {
  const pick = measures.find((m) => m.code === lead && m.value != null) ?? measures.find((m) => m.code === FALLBACK_LEAD && m.value != null)
  return pick ? moveSentence(pick.code, pick.value, pick.wow, label(pick.code)) : null
}
