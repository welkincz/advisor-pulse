import { Link } from 'react-router-dom'
import { TrendChart } from '../../components/charts/TrendChart'
import { Delta, Explain } from '../../components/primitives'
import { KPI_LABELS, formatKpi, happened } from '../../data'
import { REGION_ORDER } from '../../data/regions'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { LOWER_IS_BETTER } from './kpis'

function series(rows: readonly WeeklyReport[], nodeId: string, code: KpiCode, weeks: readonly string[]) {
  const byWeek = new Map(rows.filter((r) => r.node_id === nodeId && r.kpi_code === code).map((r) => [r.iso_week_id, r]))
  return weeks.map((w) => byWeek.get(w))
}

/**
 * One small chart per region (province) on a shared week axis, each with the national line
 * dashed beneath it, so "is Quebec just following the country?" is answered at a glance.
 * Ten regions are more than the four categorical colours, so every line is ink and the
 * region's name carries its identity.
 */
export function RegionMultiples({ regions, national, code, week, weeks, settled, hrefFor }: {
  regions: readonly WeeklyReport[]
  national: readonly WeeklyReport[]
  code: KpiCode
  week: string
  weeks: readonly string[]
  /** Whether `week` has a settled usual to compare with. */
  settled: boolean
  hrefFor: (id: string) => string
}) {
  const nationalLine = series(national, 'CA', code, weeks).map((r) => r?.value ?? null)
  const better = code === 'AVG_MEET_MIN' ? 'neither' : LOWER_IS_BETTER.has(code) ? 'lower' : 'higher'
  return <ul className="multiples">
    {REGION_ORDER.filter((id) => regions.some((r) => r.node_id === id)).map((id) => {
      const line = series(regions, id, code, weeks)
      const current = line[weeks.indexOf(week)]
      const name = line.find(Boolean)?.node_name ?? id
      const here = weeks.indexOf(week)
      const card = () => {
        const lines = happened({ code, value: current?.value, wow: current?.wow_pct, usual: settled ? current?.trailing_13w_avg ?? null : null, flag: current?.flag === 'ANOMALY', better })
        const country = nationalLine[here]
        return { title: name, value: formatKpi(code, current?.value), happened: country != null && current?.value != null ? [...lines, `Canada: ${formatKpi(code, country)}.`] : lines, hint: `Click to open the ${name} report.` }
      }
      return <li key={id} className="multiple">
        <Explain block card={card}>{(described) => <Link to={hrefFor(id)} className="multiple-head" {...described}>
          <span className="multiple-name">{name}</span>
          <span className="multiple-value figure-num">{formatKpi(code, current?.value)}</span>
          <Delta value={current?.wow_pct} better={better} />
        </Link>}</Explain>
        <TrendChart compact height={84} weeks={weeks} values={line.map((r) => r?.value ?? null)} reference={nationalLine}
          flagged={line.map((r) => r?.flag === 'ANOMALY')} selected={week} morphKey={code}
          format={(v) => formatKpi(code, v)} label={`${name}, ${KPI_LABELS[code].toLowerCase()} over ${weeks.length} weeks, with the national line for comparison`} />
      </li>
    })}
  </ul>
}
