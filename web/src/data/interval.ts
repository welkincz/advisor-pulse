import { formatKpi } from './kpi'

/** The normal quantile for a two-sided 95% interval, as in scripts/shrinkage_eval.py. */
const Z95 = 1.96

/**
 * A 95% range wider than this (as a share, so 0.15 is 15 points) is too wide to read: it is
 * wider than the middle half of advisors spans, so it cannot even place a book in a quartile
 * (ADR 0008).
 */
export const TOO_WIDE = 0.15

export interface Interval { low: number; high: number }

/**
 * The Wilson score interval for `k` successes in `n` trials: unlike the plain ±1.96·SE, it
 * stays inside 0–1 and is honest near 0% and 100% and for small `n`. Null when `n` is 0.
 */
export function wilson(k: number, n: number, z = Z95): Interval | null {
  if (!(n > 0) || k < 0 || k > n) return null
  const p = k / n
  const z2 = z * z
  const centre = (p + z2 / (2 * n)) / (1 + z2 / n)
  const half = (z / (1 + z2 / n)) * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))
  return { low: Math.max(0, centre - half), high: Math.min(1, centre + half) }
}

/** Counts behind the lead KPI, as the marts export them. */
export interface ContactCounts { contacted: number; clients: number }

/** The counts from an exported row (org, advisor or FSA), when the week has a 12-month rate. */
export function contactCounts(row: { portfolio_clients: number; portfolio_contacted_12m: number; portfolio_contacted_rate_12m?: number | null } | null | undefined): ContactCounts | null {
  return row && row.portfolio_contacted_rate_12m != null ? { contacted: row.portfolio_contacted_12m, clients: row.portfolio_clients } : null
}

/** "83.1–85.3%": the lead KPI's range, written the way its value is. */
export function formatRange({ low, high }: Interval): string {
  return `${formatKpi('PRTF_CONTACT_12M', low).replace('%', '')}–${formatKpi('PRTF_CONTACT_12M', high)}`
}

/**
 * The hover-card line for the 12-month contacted rate: its likely range, or plainly that the
 * book is too small to read. Null when there is nothing to say (no clients).
 */
export function rangeLine(counts: ContactCounts | null | undefined): string | null {
  if (!counts) return null
  const range = wilson(counts.contacted, counts.clients)
  if (!range) return null
  const clients = counts.clients.toLocaleString('en-CA')
  return range.high - range.low > TOO_WIDE
    ? `Too few clients (${clients}) to read: likely ${formatRange(range)}.`
    : `Likely ${formatRange(range)}, from ${clients} clients.`
}
