import { formatChange, formatKpi } from '../../data/kpi'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'

/**
 * "Show the numbers" for a weekly line: every week's value, usual and change, newest first, the
 * chosen week marked. It is the chart's accessible view, written with the same formatters.
 */
export function SeriesTable({ rows, code, week, settled, label }: { rows: readonly (WeeklyReport | undefined)[]; code: KpiCode; week: string; settled: ReadonlySet<string>; label: string }) {
  return <details className="figure-table hero-table">
    <summary>Show the numbers</summary>
    <div className="hero-table-scroll" tabIndex={0} role="region" aria-label={label}>
      <table><thead><tr><th scope="col">Week</th><th scope="col" className="num">Value</th><th scope="col" className="num">Usual</th><th scope="col" className="num">WoW</th><th scope="col">Flag</th></tr></thead>
        <tbody>{[...rows].reverse().map((r) => r && <tr key={r.iso_week_id} data-week={r.iso_week_id} aria-current={r.iso_week_id === week ? 'true' : undefined}>
          <th scope="row">{r.iso_week_id}</th><td className="num">{formatKpi(code, r.value)}</td>
          <td className="num">{settled.has(r.iso_week_id) ? formatKpi(code, r.trailing_13w_avg) : '–'}</td>
          <td className="num">{r.wow_pct == null ? '–' : formatChange(r.wow_pct)}</td><td>{r.flag === 'ANOMALY' ? 'Anomaly' : ''}</td>
        </tr>)}</tbody></table>
    </div>
  </details>
}
