import type { WeeklyReport } from '../../data/generated/weekly_report'
import { downloadCsv, toCsv } from '../../data/csv'

/** Download one node's weekly series for a measure: raw values, as the export holds them. */
export function SeriesCsvButton({ rows, filename }: { rows: readonly (WeeklyReport | undefined)[]; filename: string }) {
  const present = rows.filter((r): r is WeeklyReport => r !== undefined)
  return <button type="button" className="csv-button" disabled={!present.length}
    onClick={() => downloadCsv(filename, toCsv(
      ['iso_week_id', 'node_id', 'node_name', 'kpi_code', 'value', 'prior_week_value', 'wow_pct', 'trailing_13w_avg', 'flag'],
      present.map((r) => [r.iso_week_id, r.node_id, r.node_name, r.kpi_code, r.value, r.prior_week_value, r.wow_pct, r.trailing_13w_avg, r.flag]),
    ))}>
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M8 2v8m-3-3 3 3 3-3M3 13h10" /></svg>
    Download CSV
  </button>
}
