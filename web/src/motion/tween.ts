/** cubic-bezier(x1, y1, x2, y2) as a function of progress, solved for x by Newton's method. */
export function cubicBezier(x1: number, y1: number, x2: number, y2: number): (t: number) => number {
  const at = (a: number, b: number, s: number) => 3 * a * s * (1 - s) ** 2 + 3 * b * s * s * (1 - s) + s ** 3
  const slope = (a: number, b: number, s: number) => 3 * a * (1 - s) ** 2 + 6 * (b - a) * s * (1 - s) + 3 * (1 - b) * s * s
  return (t) => {
    if (t <= 0) return 0
    if (t >= 1) return 1
    let s = t
    for (let i = 0; i < 8; i++) {
      const d = slope(x1, x2, s)
      if (Math.abs(d) < 1e-6) break
      s -= (at(x1, x2, s) - t) / d
    }
    return at(y1, y2, Math.min(1, Math.max(0, s)))
  }
}

export const standardEase = cubicBezier(0.2, 0, 0, 1)

/** Tween from `from` to `to` on animation frames; returns a stop function. */
export function tween(from: number, to: number, duration: number, onFrame: (value: number) => void): () => void {
  let frame = 0
  let start: number | null = null
  // Time from the first frame's own timestamp, so progress never starts below 0.
  const step = (now: number) => {
    start ??= now
    const progress = Math.min(1, (now - start) / duration)
    onFrame(from + (to - from) * standardEase(progress))
    if (progress < 1) frame = requestAnimationFrame(step)
  }
  frame = requestAnimationFrame(step)
  return () => cancelAnimationFrame(frame)
}
