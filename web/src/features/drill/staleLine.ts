/** Below this (0.05 points) a 13-week change reads as no change. */
const STEADY = 0.0005

const pct = (share: number) => `${(share * 100).toFixed(1)}%`

/**
 * The branch's stale-book line: the share of its book with no contact in 9+ months and how
 * that moved over 13 weeks. A secondary measure, never worded as a forecast. Null when the
 * week has no value (a non-branch row, or no 12-month window yet).
 */
export function staleBookLine(share: number | null | undefined, rise: number | null | undefined): { value: string; change: string | null } | null {
  if (share === null || share === undefined) return null
  if (rise === null || rise === undefined) return { value: pct(share), change: null }
  const points = Math.abs(rise * 100).toFixed(1)
  const change = Math.abs(rise) < STEADY ? 'about the same as 13 weeks earlier'
    : `${rise > 0 ? 'up' : 'down'} ${points} pts in 13 weeks`
  return { value: pct(share), change }
}
