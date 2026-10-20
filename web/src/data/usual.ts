import { fenced } from '../components/charts/scale'
import type { KpiCode, WeeklyReport } from './generated/weekly_report'

/** A trailing 13-week average needs 13 weeks behind it; before that there is no "usual" yet. */
export const WARM_UP_WEEKS = 13

/** The weeks that have a full 13 weeks of history behind them. */
export function settledWeeks(weeks: readonly string[]): Set<string> {
  return new Set(weeks.slice(WARM_UP_WEEKS))
}

/** How far a week sits from the area's own trailing 13-week average, as a share; null without one. */
export function versusUsual(row: WeeklyReport): number | null {
  const usual = row.trailing_13w_avg
  return row.value == null || usual == null || usual === 0 ? null : row.value / usual - 1
}

/**
 * Half-width of the diverging scale: the largest typical distance from usual across every
 * week in view, inside Tukey's fences, so one odd week does not flatten the rest.
 */
export function deviationReach(rows: readonly WeeklyReport[], code: KpiCode): number | null {
  const range = fenced(rows.filter((row) => row.kpi_code === code).map(versusUsual))
  if (!range) return null
  return Math.max(Math.abs(range[0]), Math.abs(range[1])) || null
}

/**
 * A step on the seven-step diverging scale: 0 is far worse than usual, 3 is a usual week,
 * 6 is far better. "Better" follows the KPI's direction.
 */
export function usualStep(deviation: number | null, reach: number | null, lowerIsBetter: boolean): number | null {
  if (deviation === null || !reach) return null
  const good = lowerIsBetter ? -deviation : deviation
  return Math.max(-3, Math.min(3, Math.round((good / reach) * 3))) + 3
}
