/** The recap JSON written by `pulse recap` (src/pulse/export/recap.py). */
export interface RecapKpi {
  code: string
  label: string
  value: number | null
  text: string
  wow: number | null
  better: 'higher' | 'lower'
  flag: boolean
}

export interface RecapRegion { id: string; name: string; away: number | null; text: string; flag: boolean }

export interface RecapProps {
  version: number
  week: string
  dates: string
  headline: string
  support: string
  kpis: RecapKpi[]
  rankedLabel: string
  regions: RecapRegion[]
  flagged: { name: string; label: string; wow: number | null }[]
  summary: string | null
  [key: string]: unknown
}

/** Rates print as percentages, averages with one decimal, counts as whole numbers. */
export function formatLike(code: string, value: number): string {
  const rates = ['CALL_TO_APPT', 'SHOW_RATE', 'APPT_CONV', 'NO_SHOW_RATE', 'LATE_RATE', 'QUAR_RATE']
  if (rates.includes(code)) return `${(value * 100).toFixed(1)}%`
  if (code === 'ACT_PER_ADV' || code === 'AVG_MEET_MIN') return value.toFixed(1)
  return Math.round(value).toLocaleString('en-CA')
}

export const pct = (share: number) => `${share > 0 ? '+' : share < 0 ? '−' : '±'}${Math.abs(share * 100).toFixed(1)}%`
