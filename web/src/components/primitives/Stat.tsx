import type { HTMLAttributes, ReactNode } from 'react'

/** One KPI: name, value in tabular figures, then context (a Delta, a Sparkline) underneath. */
/** `footer` is a last, block-level description (a definition); other props go on the group div. */
export function Stat({ label, value, unit, children, footer, emphasis = false, ...rest }: { label: string; value: string; unit?: string; children?: ReactNode; footer?: ReactNode; emphasis?: boolean } & Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'className'>) {
  return <div {...rest} className={emphasis ? 'stat stat-emphasis' : 'stat'}>
    <dt className="stat-label">{label}</dt>
    <dd className="stat-value figure-num">{value}{unit && <span className="stat-unit">{unit}</span>}</dd>
    {children && <dd className="stat-context">{children}</dd>}
    {footer && <dd className="stat-footer">{footer}</dd>}
  </div>
}

/** A row of Stats; it is a description list, so screen readers pair each label with its value. */
export function StatGroup({ children, label }: { children: ReactNode; label: string }) {
  return <dl className="stat-group" aria-label={label}>{children}</dl>
}
