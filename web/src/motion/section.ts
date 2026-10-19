import type { CSSProperties } from 'react'

/** Opacity only: entry order is visible without changing layout geometry. See motion.css. */
export function sectionEntrance(order: number, reducedMotion: boolean): { className: string; style?: CSSProperties } {
  if (reducedMotion) return { className: '' }
  return { className: 'section-reveal', style: { animationDelay: `${Math.min(order, 3) * 80}ms` } }
}
