import { Link } from 'react-router-dom'
import { TrendChart } from '../../components/charts/TrendChart'
import { Delta } from '../../components/primitives'
import { KPI_LABELS, formatKpi } from '../../data'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { LOWER_IS_BETTER } from '../overview/kpis'

/**
 * One small chart per child on a shared week axis, best first, each over this node's line
 * (dashed), so a reader sees which children carry the trend and which buck it.
 */
export function ChildMultiples({ rows, parent, code, week, weeks, hrefFor, onOpen }: {
  rows: readonly WeeklyReport[]
  parent: readonly (number | null)[]
  code: KpiCode
  week: string
  weeks: readonly string[]
  hrefFor: (id: string) => string
  onOpen?: (event: React.MouseEvent<HTMLAnchorElement>, href: string) => void
}) {
  const byNode = new Map<string, Map<string, WeeklyReport>>()
  for (const row of rows) {
    if (row.kpi_code !== code) continue
    let weeksOf = byNode.get(row.node_id)
    if (!weeksOf) byNode.set(row.node_id, weeksOf = new Map())
    weeksOf.set(row.iso_week_id, row)
  }
  const lower = LOWER_IS_BETTER.has(code)
  const better = code === 'AVG_MEET_MIN' ? 'neither' : lower ? 'lower' : 'higher'
  const children = [...byNode].map(([id, weeksOf]) => ({ id, weeksOf, now: weeksOf.get(week), name: [...weeksOf.values()][0]!.node_name }))
    // Best first in the KPI's direction; children with no value this week go last.
    .sort((a, b) => {
      const av = a.now?.value ?? null
      const bv = b.now?.value ?? null
      if (av === null || bv === null) return Number(av === null) - Number(bv === null) || a.name.localeCompare(b.name)
      return (lower ? av - bv : bv - av) || a.name.localeCompare(b.name)
    })
  if (!children.length) return <p>No children reported {KPI_LABELS[code].toLowerCase()} in these weeks.</p>
  return <ul className="multiples child-multiples">
    {children.map(({ id, weeksOf, now, name }) => {
      const href = hrefFor(id)
      return <li key={id} className="multiple">
        <Link to={href} className="multiple-head" onClick={onOpen && ((event) => onOpen(event, href))}>
          <span className="multiple-name">{name}</span>
          <span className="multiple-value figure-num">{formatKpi(code, now?.value)}</span>
          <Delta value={now?.wow_pct} better={better} />
        </Link>
        <TrendChart compact height={72} weeks={weeks} values={weeks.map((w) => weeksOf.get(w)?.value ?? null)} reference={parent}
          flagged={weeks.map((w) => weeksOf.get(w)?.flag === 'ANOMALY')} selected={week} morphKey={code}
          format={(v) => formatKpi(code, v)} label={`${name}, ${KPI_LABELS[code].toLowerCase()} over ${weeks.length} weeks, with the parent's line for comparison`} />
      </li>
    })}
  </ul>
}
