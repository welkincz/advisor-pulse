import { Link } from 'react-router-dom'
import { TrendChart } from '../../components/charts/TrendChart'
import { Delta } from '../../components/primitives'
import { KPI_LABELS, formatKpi } from '../../data'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { LOWER_IS_BETTER } from './kpis'

/** Regions in their fixed identity order (docs/design.md §6): the colour follows the region. */
export const REGION_ORDER = ['ON', 'QC', 'WE', 'AT'] as const
const COLOUR: Record<string, string> = { ON: 'var(--series-1)', QC: 'var(--series-2)', WE: 'var(--series-3)', AT: 'var(--series-4)' }

function series(rows: readonly WeeklyReport[], nodeId: string, code: KpiCode, weeks: readonly string[]) {
  const byWeek = new Map(rows.filter((r) => r.node_id === nodeId && r.kpi_code === code).map((r) => [r.iso_week_id, r]))
  return weeks.map((w) => byWeek.get(w))
}

/**
 * One small chart per region on a shared week axis, each with the national line dashed
 * beneath it, so "is Quebec just following the country?" is answered at a glance.
 */
export function RegionMultiples({ regions, national, code, week, weeks, hrefFor }: {
  regions: readonly WeeklyReport[]
  national: readonly WeeklyReport[]
  code: KpiCode
  week: string
  weeks: readonly string[]
  hrefFor: (id: string) => string
}) {
  const nationalLine = series(national, 'CA', code, weeks).map((r) => r?.value ?? null)
  const better = code === 'AVG_MEET_MIN' ? 'neither' : LOWER_IS_BETTER.has(code) ? 'lower' : 'higher'
  return <ul className="multiples">
    {REGION_ORDER.map((id) => {
      const line = series(regions, id, code, weeks)
      const current = line[weeks.indexOf(week)]
      const name = line.find(Boolean)?.node_name ?? id
      return <li key={id} className="multiple">
        <Link to={hrefFor(id)} className="multiple-head">
          <span className="multiple-name"><i className="multiple-key" style={{ background: COLOUR[id] }} aria-hidden="true" />{name}</span>
          <span className="multiple-value figure-num">{formatKpi(code, current?.value)}</span>
          <Delta value={current?.wow_pct} better={better} />
        </Link>
        <TrendChart compact height={84} weeks={weeks} values={line.map((r) => r?.value ?? null)} reference={nationalLine}
          flagged={line.map((r) => r?.flag === 'ANOMALY')} selected={week} color={COLOUR[id]} morphKey={code}
          format={(v) => formatKpi(code, v)} label={`${name}, ${KPI_LABELS[code].toLowerCase()} over ${weeks.length} weeks, with the national line for comparison`} />
      </li>
    })}
  </ul>
}
