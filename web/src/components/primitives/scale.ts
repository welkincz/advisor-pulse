/**
 * The extent inside Tukey's fences (1.5 × IQR beyond the quartiles). Warm-up weeks, such as
 * 13-week coverage climbing from zero, would otherwise squeeze every real week into one shade.
 */
export function fenced(values: Iterable<number | null>): [number, number] | null {
  const known = [...values].filter((value): value is number => value !== null && Number.isFinite(value)).sort((a, b) => a - b)
  if (!known.length) return null
  const quantile = (q: number) => {
    const at = (known.length - 1) * q
    const lo = Math.floor(at)
    return known[lo]! + (known[Math.min(lo + 1, known.length - 1)]! - known[lo]!) * (at - lo)
  }
  const q1 = quantile(0.25)
  const q3 = quantile(0.75)
  const reach = 1.5 * (q3 - q1)
  const inside = known.filter((value) => value >= q1 - reach && value <= q3 + reach)
  return [inside[0]!, inside.at(-1)!]
}
