import { Explain } from '../../components/primitives'
import { useOrgWeekly } from '../../data'
import { staleBookLine } from './staleLine'

const TITLE = 'No contact in 9+ months'

/** One quiet line under a branch's measures: how much of its book is close to leaving the 12-month window. */
export function StaleBook({ branchId, week }: { branchId: string; week: string }) {
  const result = useOrgWeekly(branchId, [week])
  const row = result.status === 'ready' ? result.data.find((r) => r.iso_week_id === week) : undefined
  const line = staleBookLine(row?.stale_9m_share, row?.stale_9m_rise_13w)
  if (!line) return null
  return <p className="stale-book" data-measure="stale-9m">
    <Explain card={{
      title: TITLE,
      value: line.value,
      what: 'Clients in this branch’s portfolios whose last contact was 9 or more months ago. Unless someone reaches them, they drop out of portfolio contacted (12 months) within 3 months.',
      answer: { q: 'Is this a forecast?', a: 'No. It is a secondary measure of the book as it stands this week, not a prediction for the branch.' },
    }}>
      {(described) => <span className="term" tabIndex={0} {...described}>{TITLE}</span>}
    </Explain>
    {': '}<span className="figure-num">{line.value}</span>
    {line.change && <span className="stale-book-change"> ({line.change})</span>}
  </p>
}
