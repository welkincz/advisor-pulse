import { Delta, Sparkline } from '../../components/primitives'
import { KPI_LABELS } from '../../data'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { AnimatedKpiValue } from '../../motion/AnimatedKpiValue'
import { LOWER_IS_BETTER } from './kpis'

const SPARK_WEEKS = 26

/** The twelve measures in three plain groups: who was reached, what came of it, how clean the data was. */
export const KPI_GROUPS: readonly { title: string; codes: readonly KpiCode[] }[] = [
  { title: 'Reach', codes: ['ACT_PER_ADV', 'CALLS_OUT', 'CLIENTS_CONTACTED', 'COVERAGE_13W'] },
  { title: 'Appointments', codes: ['APPT_BOOKED', 'CALL_TO_APPT', 'SHOW_RATE', 'NO_SHOW_RATE', 'APPT_CONV', 'AVG_MEET_MIN'] },
  { title: 'Data quality', codes: ['LATE_RATE', 'QUAR_RATE'] },
]

export interface BoardRow { value: number | null; wow: number | null; flag: boolean; trend: (number | null)[] }

/** Board rows for `week`: the value, its change, its flag and the trend up to it. */
export function boardRows(history: readonly WeeklyReport[], weeks: readonly string[], week: string): Map<KpiCode, BoardRow> {
  const end = weeks.indexOf(week)
  const window = weeks.slice(Math.max(0, end - SPARK_WEEKS + 1), end + 1)
  const byCode = new Map<KpiCode, Map<string, WeeklyReport>>()
  for (const row of history) {
    let weeksOf = byCode.get(row.kpi_code)
    if (!weeksOf) byCode.set(row.kpi_code, weeksOf = new Map())
    weeksOf.set(row.iso_week_id, row)
  }
  return new Map([...byCode].map(([code, weeksOf]) => {
    const current = weeksOf.get(week)
    return [code, {
      value: current?.value ?? null,
      wow: current?.wow_pct ?? null,
      flag: current?.flag === 'ANOMALY',
      trend: window.map((w) => weeksOf.get(w)?.value ?? null),
    }]
  }))
}

/**
 * Every measure for the week, each a row with its 26-week trend. A row is also the switch
 * for the chart above: choosing it plots that measure there.
 */
export function KpiBoard({ rows, selected, onSelect, only }: { rows: Map<KpiCode, BoardRow>; selected: KpiCode; onSelect: (code: KpiCode) => void; only?: readonly KpiCode[] }) {
  // Below the national level the batch-wide rates do not exist, so their group is left out.
  const groups = KPI_GROUPS.map((g) => ({ ...g, codes: only ? g.codes.filter((c) => only.includes(c)) : g.codes })).filter((g) => g.codes.length)
  return <div className="board">
    {groups.map((group) => <section key={group.title} className="board-group" aria-labelledby={`board-${group.title}`}>
      <h3 id={`board-${group.title}`}>{group.title}</h3>
      <ul>
        {group.codes.map((code) => {
          const row = rows.get(code)
          const better = code === 'AVG_MEET_MIN' ? 'neither' : LOWER_IS_BETTER.has(code) ? 'lower' : 'higher'
          return <li key={code} data-kpi={code}>
            <button type="button" className="board-row" aria-pressed={code === selected} onClick={() => onSelect(code)}>
              <span className="board-label">{KPI_LABELS[code]}{row?.flag && <span className="board-flag">Anomaly</span>}</span>
              <span className="board-value figure-num"><AnimatedKpiValue code={code} value={row?.value ?? null} /></span>
              <span className="board-spark">{row && <Sparkline values={row.trend} label={`${KPI_LABELS[code]}, last ${row.trend.length} weeks`} width={88} height={22} />}</span>
              <span className="board-delta"><Delta value={row?.wow} better={better} />{row?.wow != null && <span className="board-wow"> WoW</span>}</span>
            </button>
          </li>
        })}
      </ul>
    </section>)}
  </div>
}
