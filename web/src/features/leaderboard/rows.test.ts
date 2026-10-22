import { describe, expect, it } from 'vitest'
import type { AdvisorWeekly } from '../../data/generated/advisor_weekly'
import type { WeeklyReport } from '../../data/generated/weekly_report'
import { ADVISOR_KPIS, advisorRows, denseRank, orgRows, rankChange } from './rows'

const WEEKS = ['2026-W39', '2026-W40']

function report(node: string, week: string, value: number | null, rank: number | null, code: WeeklyReport['kpi_code'] = 'CALLS_OUT'): WeeklyReport {
  return { iso_week_id: week, level: 'DISTRICT', node_id: node, node_name: `${node} district`, parent_id: 'ON', kpi_code: code, value, rank_in_parent: rank, peer_count: 3, flag: 'FLAT' } as WeeklyReport
}

function advisor(id: string, week: string, held: number, noShows: number): AdvisorWeekly {
  return {
    iso_week_id: week, advisor_id: id, branch_id: 'BR-0101', district_code: 'GTA', region_code: 'ON',
    activities_completed: 10, calls_out: 5, calls_in: 2, appointments_booked: 3, appointments_held: held, no_shows: noShows,
    conversions: 1, unique_clients_contacted: 4, avg_meeting_duration_min: 40,
    portfolio_clients: 100, portfolio_contacted_12m: 80, portfolio_contacted_rate_12m: 0.8,
  }
}

describe('denseRank', () => {
  it('ranks higher first by default and lower first when lower is better, with ties sharing a rank', () => {
    const values = new Map<string, number | null>([['a', 0.1], ['b', 0.3], ['c', 0.1], ['d', null]])
    expect(Object.fromEntries(denseRank(values, 'SHOW_RATE'))).toEqual({ a: 2, b: 1, c: 2 })
    expect(Object.fromEntries(denseRank(values, 'NO_SHOW_RATE'))).toEqual({ a: 1, b: 2, c: 1 })
  })
})

describe('orgRows', () => {
  it('uses the mart rank, orders by it, and compares with the prior week', () => {
    const rows = orgRows([
      report('GTA', '2026-W39', 90, 1), report('GTA', '2026-W40', 80, 2),
      report('EON', '2026-W39', 70, 2), report('EON', '2026-W40', 95, 1),
      report('NEW', '2026-W40', null, null),
      report('GTA', '2026-W40', 0.5, 1, 'SHOW_RATE'),
    ], 'CALLS_OUT', WEEKS)
    expect(rows.map((r) => [r.id, r.rank, rankChange(r)])).toEqual([['EON', 1, 1], ['GTA', 2, -1], ['NEW', null, null]])
    expect(rows[0]!.trend).toEqual([70, 95])
    expect(rows[0]!.name).toBe('EON district')
  })
})

describe('advisorRows', () => {
  it('ranks no-show rate lowest first and show rate highest first', () => {
    const history = [advisor('ADV-1', '2026-W40', 9, 1), advisor('ADV-2', '2026-W40', 6, 4), advisor('ADV-3', '2026-W40', 0, 0)]
    const noShow = advisorRows(history, 'NO_SHOW_RATE', WEEKS)
    expect(noShow.map((r) => [r.id, r.value, r.rank])).toEqual([['ADV-1', 0.1, 1], ['ADV-2', 0.4, 2], ['ADV-3', null, null]])
    expect(advisorRows(history, 'SHOW_RATE', WEEKS).map((r) => r.id)).toEqual(['ADV-1', 'ADV-2', 'ADV-3'])
  })

  it('offers only KPIs that advisor_weekly can compute', () => {
    expect(ADVISOR_KPIS).not.toContain('CALL_TO_APPT')
    expect(advisorRows([advisor('ADV-1', '2026-W40', 1, 0)], 'CALL_TO_APPT', WEEKS)).toEqual([])
  })
})
