/** Small, dependency-free scale helpers for the hand-drawn SVG charts. */

/** Round tick values ("nice numbers") covering [lo, hi], about `count` of them. */
export function ticks(lo: number, hi: number, count = 4): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return []
  if (lo === hi) return [lo]
  const step = niceStep(lo, hi, count)
  const out: number[] = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Number(v.toPrecision(12)))
  return out
}

/** The round step (1, 2, 2.5 or 5 times a power of ten) that cuts [lo, hi] into about `count` parts. */
function niceStep(lo: number, hi: number, count: number): number {
  const raw = (hi - lo) / Math.max(1, count)
  const power = 10 ** Math.floor(Math.log10(raw))
  return [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? 10 * power
}

/**
 * A value axis fitted to the data, for marks that do not encode length (dots, lines): the
 * padded extent widened to round ticks at both ends. It does not cross zero when the data
 * does not, so a share never shows a negative tick. Bars keep a zero baseline instead.
 */
export function fitted(values: Iterable<number | null | undefined>, count = 4, pad = 0.15): { lo: number; hi: number; ticks: number[] } | null {
  const known = [...values].filter((v): v is number => v != null && Number.isFinite(v))
  const padded = domain(known, pad)
  if (!padded) return null
  const step = niceStep(padded[0], padded[1], count)
  const round = (v: number) => Number(v.toPrecision(12))
  let lo = round(Math.floor(padded[0] / step + 1e-9) * step)
  let hi = round(Math.ceil(padded[1] / step - 1e-9) * step)
  if (lo < 0 && Math.min(...known) >= 0) lo = 0
  if (hi > 0 && Math.max(...known) <= 0) hi = 0
  const out: number[] = []
  for (let k = Math.ceil(lo / step - 1e-9); k * step <= hi + step * 1e-9; k++) out.push(round(k * step))
  return { lo, hi, ticks: out }
}

/** The [min, max] of the known values, padded by `pad` of the span on each side. */
export function domain(values: Iterable<number | null | undefined>, pad = 0.08): [number, number] | null {
  let lo = Infinity
  let hi = -Infinity
  for (const v of values) {
    if (v == null || !Number.isFinite(v)) continue
    lo = Math.min(lo, v)
    hi = Math.max(hi, v)
  }
  if (!Number.isFinite(lo)) return null
  const span = hi - lo || Math.abs(hi) || 1
  return [lo - span * pad, hi + span * pad]
}

export type Pt = [number, number] | null

/** SVG path through the points; a null point breaks the line. */
export function linePath(points: readonly Pt[]): string {
  let d = ''
  let open = false
  for (const p of points) {
    if (!p) { open = false; continue }
    d += `${open ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`
    open = true
  }
  return d
}

/** Interpolate two point lists of equal length; a point missing on either side is missing. */
export function mixPoints(from: readonly Pt[], to: readonly Pt[], t: number): Pt[] {
  return to.map((b, i) => {
    const a = from[i]
    if (!b) return null
    if (!a) return b
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
  })
}

/**
 * The extent inside Tukey's fences (1.5 × IQR beyond the quartiles). Warm-up weeks, such as
 * a rate whose window is still filling, would otherwise squeeze every real week into one shade.
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

/**
 * The one flagged week a full chart circles: the selected week when it is flagged (that is the
 * week being read), else the latest flagged week with a value. Null when none is flagged.
 */
export function annotatedWeek(flagged: readonly boolean[] | undefined, values: readonly (number | null)[], selected: number): number | null {
  if (!flagged) return null
  if (selected >= 0 && flagged[selected] && values[selected] != null) return selected
  for (let i = flagged.length - 1; i >= 0; i--) if (flagged[i] && values[i] != null) return i
  return null
}
