import type { ReactNode } from 'react'

/** A report section: the heading and its lede sit in the margin column, the content beside it. */
export function Section({ id, title, lede, children }: { id: string; title: string; lede?: ReactNode; children: ReactNode }) {
  return <section className="section" aria-labelledby={`${id}-title`}>
    <header className="section-margin">
      <h2 id={`${id}-title`}>{title}</h2>
      {lede && <p className="section-lede">{lede}</p>}
    </header>
    <div className="section-body">{children}</div>
  </section>
}
