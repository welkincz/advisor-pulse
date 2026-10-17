import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Section, Sparkline } from '../../components/primitives'
import { DataNotice, type DataResult, KPI_LABELS, formatKpi, useAdvisorWeekly, useChildReportHistory } from '../../data'
import type { KpiCode } from '../../data/generated/weekly_report'
import { LOWER_IS_BETTER } from '../overview/kpis'
import { ADVISOR_KPIS, type LeaderRow, ORG_KPIS, advisorRows, orgRows, rankChange } from './rows'
import './leaderboard.css'

const TREND_WEEKS = 8
/** Above this many rows only the rows in view are rendered. */
export const VIRTUAL_AFTER = 100
const ROW_HEIGHT = 44
const VIEW_ROWS = 12
const OVERSCAN = 6

interface Props {
  /** Weeks with data, oldest first; the last is the reporting week. */
  weeks: readonly string[]
  parentId: string
  parentName: string
  /** Where a child row links to, if anywhere. */
  childHref?: (id: string) => string
}

function Change({ row }: { row: LeaderRow }) {
  const change = rankChange(row)
  if (change === null) return <span className="leader-muted">{row.rank === null ? '–' : 'new'}</span>
  if (change === 0) return <span className="leader-muted" aria-label="No change">=</span>
  const up = change > 0
  return <span aria-label={`${up ? 'Up' : 'Down'} ${Math.abs(change)}`}>{up ? '▲' : '▼'} {Math.abs(change)}</span>
}

/** Rows to render: all of them, or the window in view plus spacers when there are many. */
function useWindow(count: number) {
  const [top, setTop] = useState(0)
  if (count <= VIRTUAL_AFTER) return { virtual: false, start: 0, end: count, onScroll: undefined }
  const start = Math.max(0, Math.floor(top / ROW_HEIGHT) - OVERSCAN)
  const end = Math.min(count, start + VIEW_ROWS + 2 * OVERSCAN)
  return { virtual: true, start, end, onScroll: (event: React.UIEvent<HTMLDivElement>) => setTop(event.currentTarget.scrollTop) }
}

export function LeaderTable({ rows, code, caption, childHref }: { rows: LeaderRow[]; code: KpiCode; caption: string; childHref?: (id: string) => string }) {
  const { virtual, start, end, onScroll } = useWindow(rows.length)
  const label = KPI_LABELS[code]
  const table = <table className="leader-table" aria-rowcount={rows.length + 1}>
    <caption>{caption}. Trend covers the last {TREND_WEEKS} weeks.</caption>
    <thead><tr aria-rowindex={1}>
      <th scope="col" className="num">Rank</th>
      <th scope="col">Change</th>
      <th scope="col">Name</th>
      <th scope="col" className="num">Value</th>
      <th scope="col">Trend</th>
    </tr></thead>
    <tbody>
      {virtual && start > 0 && <tr aria-hidden="true" style={{ height: start * ROW_HEIGHT }} />}
      {rows.slice(start, end).map((row, offset) => <tr key={row.id} aria-rowindex={start + offset + 2} style={virtual ? { height: ROW_HEIGHT } : undefined}>
        <td className="num figure-num">{row.rank ?? '–'}</td>
        <td><Change row={row} /></td>
        <th scope="row">{childHref ? <Link to={childHref(row.id)}>{row.name}</Link> : row.name}</th>
        <td className="num figure-num">{formatKpi(code, row.value)}</td>
        <td><Sparkline width={64} values={row.trend} label={`${row.name}, ${label} over ${row.trend.length} weeks`} /></td>
      </tr>)}
      {virtual && end < rows.length && <tr aria-hidden="true" style={{ height: (rows.length - end) * ROW_HEIGHT }} />}
    </tbody>
  </table>
  if (!virtual) return <div className="leader-wrap">{table}</div>
  return <div className="leader-wrap leader-scroll" style={{ maxHeight: ROW_HEIGHT * (VIEW_ROWS + 1) }} onScroll={onScroll}
    tabIndex={0} role="region" aria-label={`${caption}, scrollable`}>{table}</div>
}

function Board({ title, codes, result, toRows, weeks, parentName, childHref }: {
  title: string
  codes: readonly KpiCode[]
  result: DataResult<unknown[]>
  toRows: (code: KpiCode) => LeaderRow[]
  weeks: readonly string[]
  parentName: string
  childHref?: (id: string) => string
}) {
  const [code, setCode] = useState<KpiCode>(codes[0]!)
  const week = weeks.at(-1)
  const rows = result.status === 'ready' ? toRows(code) : []
  const direction = LOWER_IS_BETTER.has(code) ? 'lowest' : 'highest'
  return <Section id="leaderboard" title={title} lede={`Ranked ${direction} first; change is places moved since the prior week.`}>
    <label className="leader-picker">Rank by
      <select value={code} onChange={(event) => setCode(event.target.value as KpiCode)}>
        {codes.map((item) => <option key={item} value={item}>{KPI_LABELS[item]}</option>)}
      </select>
    </label>
    {result.status === 'loading' && <p aria-busy="true">Loading the ranking…</p>}
    {result.status === 'error' && <DataNotice what="the ranking" onRetry={result.retry} />}
    {(result.status === 'empty' || (result.status === 'ready' && rows.length === 0)) && <p>No ranking is available for {week}.</p>}
    {rows.length > 0 && <LeaderTable rows={rows} code={code} childHref={childHref}
      caption={`${KPI_LABELS[code]} under ${parentName}, week ${week}`} />}
  </Section>
}

/** Regions, districts or branches under an org node, ranked by the mart's rank_in_parent. */
export function OrgLeaderboard({ weeks, parentId, parentName, childHref }: Props) {
  const recent = weeks.slice(-TREND_WEEKS)
  const result = useChildReportHistory(parentId, recent)
  return <Board title="Leaderboard" codes={ORG_KPIS} result={result} weeks={recent} parentName={parentName} childHref={childHref}
    toRows={(code) => (result.status === 'ready' ? orgRows(result.data, code, recent) : [])} />
}

/** Advisors in a branch, ranked here in the same direction as the mart. */
export function AdvisorLeaderboard({ weeks, parentId, parentName, childHref }: Props) {
  const recent = weeks.slice(-TREND_WEEKS)
  const result = useAdvisorWeekly(parentId, recent)
  return <Board title="Advisor leaderboard" codes={ADVISOR_KPIS} result={result} weeks={recent} parentName={parentName} childHref={childHref}
    toRows={(code) => (result.status === 'ready' ? advisorRows(result.data, code, recent) : [])} />
}
