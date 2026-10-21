import { type ReactNode, useLayoutEffect, useRef } from 'react'
import { useReducedMotion } from '../app/useReducedMotion'

const MOVE_MS = 320

/**
 * An ordered list whose rows slide to their new place when the order changes, so a reader can
 * follow an area up or down the ranking as the weeks play (FLIP: measure, reorder, play the
 * difference). Rows are found by `data-row`. Under reduced motion they simply jump.
 */
export function FlipList({ order, className, children }: { order: readonly string[]; className?: string; children: ReactNode }) {
  const list = useRef<HTMLOListElement>(null)
  const last = useRef(new Map<string, number>())
  const reducedMotion = useReducedMotion()
  const key = order.join('|')
  useLayoutEffect(() => {
    const element = list.current
    if (!element) return
    const now = new Map<string, number>()
    for (const row of element.querySelectorAll<HTMLElement>(':scope > [data-row]')) {
      const id = row.dataset.row!
      const top = row.offsetTop
      now.set(id, top)
      const before = last.current.get(id)
      if (!reducedMotion && before !== undefined && before !== top && typeof row.animate === 'function') {
        row.animate([{ transform: `translateY(${before - top}px)` }, { transform: 'none' }], { duration: MOVE_MS, easing: 'cubic-bezier(0.2, 0, 0, 1)' })
      }
    }
    last.current = now
  }, [key, reducedMotion])
  return <ol ref={list} className={className}>{children}</ol>
}
