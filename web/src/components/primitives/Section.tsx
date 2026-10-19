import type { ReactNode } from 'react'
import { useReducedMotion } from '../../app/useReducedMotion'
import { sectionEntrance } from '../../motion/section'
import '../../motion/motion.css'

/** A report section: the heading and its lede sit in the margin column, the content beside it. */
export function Section({ id, title, lede, children, revealOrder }: { id: string; title: string; lede?: ReactNode; children: ReactNode; revealOrder?: number }) {
  const reducedMotion = useReducedMotion()
  const content = <>
    <header className="section-margin">
      <h2 id={`${id}-title`}>{title}</h2>
      {lede && <p className="section-lede">{lede}</p>}
    </header>
    <div className="section-body">{children}</div>
  </>
  if (revealOrder === undefined) return <section className="section" aria-labelledby={`${id}-title`}>{content}</section>
  const entrance = sectionEntrance(revealOrder, reducedMotion)
  return <section className={`section ${entrance.className}`.trim()} style={entrance.style} aria-labelledby={`${id}-title`}
    data-reveal-order={revealOrder}>{content}</section>
}
