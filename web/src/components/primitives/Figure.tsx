import type { ReactNode } from 'react'

/**
 * A chart or map with its title, an optional one-line reading, a source note, and the
 * same numbers as a table, so no figure depends on colour or on seeing the plot.
 */
export function Figure({ title, reading, note, table, children }: {
  title: string
  reading?: ReactNode
  note?: ReactNode
  table?: ReactNode
  children: ReactNode
}) {
  return <figure className="figure">
    <h3 className="figure-title">{title}</h3>
    {reading && <p className="figure-reading">{reading}</p>}
    <div className="figure-plot">{children}</div>
    {(note || table) && <figcaption className="figure-note">
      {note}
      {table && <details className="figure-table"><summary>Show the numbers</summary>{table}</details>}
    </figcaption>}
  </figure>
}
