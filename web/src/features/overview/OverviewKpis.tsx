import { useState } from 'react'
import type { EChartsCoreOption } from 'echarts/core'
import { Chart, Delta, Figure, Section, Stat, StatGroup } from '../../components/primitives'
import { DataNotice, KPI_LABELS, formatKpi, useWeeklyReportHistory } from '../../data'
import type { Manifest } from '../../data/generated/manifest'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { AnimatedKpiValue } from '../../motion/AnimatedKpiValue'
import { KPI_CODES, KPI_DEFINITIONS, LOWER_IS_BETTER, RATE_CODES } from './kpis'
import './overview.css'

function axisValue(code: KpiCode, value: number | null | undefined): number | null {
  if (value == null) return null
  return RATE_CODES.has(code) ? value * 100 : value
}

function trendOption(code: KpiCode, rows: WeeklyReport[]): EChartsCoreOption {
  const weeks = rows.map((row) => row.iso_week_id)
  const average = rows.map((row) => axisValue(code, row.trailing_13w_avg))
  const anomalies = rows.filter((row) => row.flag === 'ANOMALY')
  const hasAverage = average.some((value) => value !== null)
  const suffix = RATE_CODES.has(code) ? '%' : ''
  return {
    aria: { enabled: false },
    grid: { left: 8, right: hasAverage ? 72 : 40, top: 12, bottom: hasAverage ? 40 : 12, containLabel: true },
    tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => typeof value === 'number' ? formatKpi(code, RATE_CODES.has(code) ? value / 100 : value) : '–' },
    legend: hasAverage ? { data: ['Weekly value', '13-week average'], bottom: 0 } : { show: false },
    xAxis: { type: 'category', data: weeks, boundaryGap: false, axisLabel: { interval: 0, formatter: (value: string, index: number) => index === 0 || index === weeks.length - 1 ? value : '' } },
    yAxis: { type: 'value', scale: true, axisLabel: { formatter: `{value}${suffix}` } },
    series: [
      {
        name: 'Weekly value', type: 'line', data: rows.map((row) => axisValue(code, row.value)),
        endLabel: { show: true, formatter: 'Value' }, labelLayout: { moveOverlap: 'shiftY' },
        markLine: anomalies.length ? { silent: true, data: anomalies.map((row) => ({ xAxis: row.iso_week_id, label: { formatter: 'Anomaly' } })) } : undefined,
      },
      ...(hasAverage ? [{ name: '13-week average', type: 'line', data: average, lineStyle: { type: 'dashed' }, endLabel: { show: true, formatter: 'Avg' } }] : []),
    ],
  }
}

function Trend({ manifest }: { manifest: Manifest }) {
  const [code, setCode] = useState<KpiCode>('ACT_PER_ADV')
  const weeks = manifest.weeks_available.slice(-26)
  const history = useWeeklyReportHistory('CA', weeks)
  const rows = history.status === 'ready' ? history.data.filter((row) => row.kpi_code === code) : []
  const first = rows[0]
  const last = rows.at(-1)
  const anomalies = rows.filter((row) => row.flag === 'ANOMALY')
  const reading = first && last
    ? `${KPI_LABELS[code]}: ${formatKpi(code, first.value)} in ${first.iso_week_id} to ${formatKpi(code, last.value)} in ${last.iso_week_id}.`
    : ''

  return <Section id="trend" title="Weekly trend" lede="Up to 26 available weeks; the 13-week average appears when reported." revealOrder={1}>
    <label className="trend-picker">Trend KPI
      <select value={code} onChange={(event) => setCode(event.target.value as KpiCode)}>
        {KPI_CODES.map((item) => <option key={item} value={item}>{KPI_LABELS[item]}</option>)}
      </select>
    </label>
    {history.status === 'loading' && <p aria-busy="true">Loading weekly trends…</p>}
    {history.status === 'error' && <DataNotice what="the weekly trend" onRetry={history.retry} />}
    {history.status === 'empty' && <p>No weekly trend is available for this report.</p>}
    {history.status === 'ready' && rows.length === 0 && <p>No trend is available for {KPI_LABELS[code].toLowerCase()}.</p>}
    {first && last && <Figure title={`${KPI_LABELS[code]} by week`} reading={reading}
      note={<>{first.iso_week_id}–{last.iso_week_id}. {anomalies.map((row) => `Anomaly in ${row.iso_week_id}. `)}{!rows.some((row) => row.trailing_13w_avg != null) && 'A 13-week average is not available yet.'}</>}
      table={<table><thead><tr><th>Week</th><th className="num">Value</th><th className="num">13-week average</th><th>Flag</th></tr></thead><tbody>
        {rows.map((row) => <tr key={row.iso_week_id}><th scope="row">{row.iso_week_id}</th><td className="num">{formatKpi(code, row.value)}</td><td className="num">{formatKpi(code, row.trailing_13w_avg)}</td><td>{row.flag === 'ANOMALY' ? 'Anomaly' : '—'}</td></tr>)}
      </tbody></table>}>
      <Chart option={trendOption(code, rows)} label={`${reading} Trend from ${first.iso_week_id} to ${last.iso_week_id}; ${anomalies.length} anomaly flags.`} height={260} />
    </Figure>}
  </Section>
}

/** Summary uses manifest JSON for first paint; Parquet history loads underneath. */
export function OverviewKpis({ manifest }: { manifest: Manifest }) {
  const summary = new Map(manifest.summary.map((row) => [row.kpi_code, row]))
  return <>
    <Section id="national" title={`National, week ${manifest.latest_week}`} lede="Change is against the prior week. Anomaly means more than two standard deviations from the 13 weeks before." revealOrder={0}>
      <StatGroup label="National key performance indicators">
        {KPI_CODES.map((code, index) => {
          const kpi = summary.get(code)
          return <Stat key={code} data-kpi={code} label={KPI_LABELS[code]} value={<AnimatedKpiValue code={code} value={kpi?.value ?? null} />} emphasis={index === 0}
            footer={<details className="kpi-definition"><summary>Definition</summary><p>{KPI_DEFINITIONS[code]}</p></details>}>
            <Delta value={kpi?.wow_pct} better={code === 'AVG_MEET_MIN' ? 'neither' : LOWER_IS_BETTER.has(code) ? 'lower' : 'higher'} />
            {kpi?.wow_pct != null && <span> WoW</span>}
            {kpi?.flag === 'ANOMALY' && <span className="kpi-anomaly">Anomaly</span>}
          </Stat>
        })}
      </StatGroup>
    </Section>
    <Trend manifest={manifest} />
  </>
}
