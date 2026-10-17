import type { ReactNode } from 'react'

/** One KPI: name, value in tabular figures, then context (a Delta, a Sparkline) underneath. */
export function Stat({ label, value, unit, children, emphasis = false }: { label: string; value: string; unit?: string; children?: ReactNode; emphasis?: boolean }) {
  return <div className={emphasis ? 'stat stat-emphasis' : 'stat'}>
    <dt className="stat-label">{label}</dt>
    <dd className="stat-value figure-num">{value}{unit && <span className="stat-unit">{unit}</span>}</dd>
    {children && <dd className="stat-context">{children}</dd>}
  </div>
}

/** A row of Stats; it is a description list, so screen readers pair each label with its value. */
export function StatGroup({ children, label }: { children: ReactNode; label: string }) {
  return <dl className="stat-group" aria-label={label}>{children}</dl>
}
