import type { KpiCode } from './generated/manifest'
import { RATES, formatKpi } from './kpi'

/**
 * Plain-language glossary for hover cards: one sentence a reader new to the report can act on.
 * The formal definitions (PLAN.md §7) stay in features/overview/kpis.ts.
 */
export const KPI_PLAIN: Record<KpiCode, string> = {
  PRTF_CONTACT_12M: 'Of the clients in advisors’ portfolios, the share who heard from an advisor at least once in the last 12 months.',
  ACT_PER_ADV: 'Calls, meetings and reviews the average advisor completed in the week.',
  CALLS_OUT: 'Outbound calls advisors completed in the week.',
  APPT_BOOKED: 'New appointments booked in the week, from any source.',
  CALL_TO_APPT: 'Of every 100 calls, how many led to a booked appointment.',
  SHOW_RATE: 'Of the meetings due in the week, the share the client attended.',
  APPT_CONV: 'Of the meetings held, the share that ended in a plan or a new product.',
  CLIENTS_CONTACTED: 'Different clients reached at least once in the week.',
  COVERAGE_13W: 'Share of advisors’ clients contacted at least once in the last 13 weeks.',
  AVG_MEET_MIN: 'How long a completed meeting lasted, on average.',
  NO_SHOW_RATE: 'Of the meetings due in the week, the share the client missed.',
  LATE_RATE: 'Share of the week’s rows that arrived after their week had closed.',
  QUAR_RATE: 'Share of the week’s rows held back because they failed a data check.',
}

/** Terms the charts use, each with the question a reader is likely to ask about it. */
export const TERMS = {
  usual: { title: 'Usual', text: 'The average of the last 13 weeks, this one included. It shows what a normal week looks like for this area.' },
  anomaly: { title: 'Anomaly', text: 'A week more than two standard deviations from the 13 weeks before it: rare enough to check. Portfolio contacted moves slowly, so for it the week’s change is what has to be unusual, and half a point or more.' },
  wow: { title: 'WoW', text: 'Week over week: the change from the week before.' },
  national: { title: 'National line', text: 'The dashed line is Canada as a whole, so you can see whether a region is just following the country.' },
  toDate: { title: 'Quarter to date', text: 'Hatched columns are quarters still running. Counts are shown as a weekly average so a part quarter compares fairly with a full one.' },
  warmUp: { title: 'No usual yet', text: 'The first 13 weeks have no full history behind them, so there is nothing to compare with yet.' },
} as const

export type Better = 'higher' | 'lower' | 'neither'

const pct = (value: number) => `${Math.abs(value * 100).toFixed(1)}%`
/**
 * Under this gap from usual (relative) the card states the gap but makes no better-or-worse
 * call. It never says "about usual" for a gap the colours or the anomaly flag treat as real.
 */
export const NO_VERDICT_BELOW = 0.015

/** "better" or "worse" for a change, judged by which way is good for the measure. */
export function verdict(change: number, better: Better): 'better' | 'worse' | 'level' {
  if (Math.abs(change) < 0.0005 || better === 'neither') return 'level'
  return (change > 0) === (better === 'higher') ? 'better' : 'worse'
}

export interface Facts {
  code: KpiCode
  value: number | null | undefined
  /** Change from the week before, as a share. */
  wow?: number | null
  /** The trailing 13-week average, when there is a settled one. */
  usual?: number | null
  flag?: boolean
  better: Better
}

/**
 * What happened, in at most three short lines: against last week, against usual, and whether
 * the week was unusual. Written from the numbers, so the card never says more than they do.
 */
export function happened({ code, value, wow, usual, flag, better }: Facts): string[] {
  if (value == null) return ['No value this week.']
  const lines: string[] = []
  if (wow != null) {
    lines.push(Math.abs(wow) < 0.0005 ? 'Level with last week.' : `${wow > 0 ? 'Up' : 'Down'} ${pct(wow)} on last week.`)
  }
  // The gap is relative, as on the map, the list and the sentence. Only a rate with a 0% usual,
  // which has nothing to divide by, is given in points.
  const rate = RATES.has(code)
  if (usual != null && (rate || usual !== 0)) {
    const points = usual === 0
    const gap = points ? value - usual : value / usual - 1
    const size = points ? `${Math.abs(gap * 100).toFixed(1)} pts` : pct(gap)
    if (size === '0.0%' || size === '0.0 pts') {
      lines.push(`Level with usual (${formatKpi(code, usual)}).`)
    } else {
      const judged = !points && Math.abs(gap) < NO_VERDICT_BELOW ? 'level' : verdict(gap, better)
      lines.push(`${size} ${gap > 0 ? 'above' : 'below'} usual (${formatKpi(code, usual)})${judged === 'level' ? '' : `: ${judged} than a normal week`}.`)
    }
  } else if (usual === null) {
    lines.push(TERMS.warmUp.text)
  }
  // The flag compares with how much this area normally moves, which a small gap can still exceed.
  if (flag) lines.push('Flagged as an anomaly: further from the 13 weeks before than this area normally moves.')
  return lines
}
