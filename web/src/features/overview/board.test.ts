// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import type { OrgWeekly } from '../../data/generated/org_weekly'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { funnelFor } from './Funnel'
import { type BoardRow, boardGroups, boardRows } from './KpiBoard'

// theme/tokens (reached through the primitives index) reads matchMedia at module load; jsdom has none.
vi.hoisted(() => {
  window.matchMedia ??= (() => ({ matches: false, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
})

const report = (iso_week_id: string, kpi_code: KpiCode, value: number | null, extra: Partial<WeeklyReport> = {}) =>
  ({ iso_week_id, kpi_code, value, wow_pct: 0.1, flag: 'NONE', trailing_13w_avg: 0.5, ...extra }) as WeeklyReport

it('builds board rows up to the chosen week, with gaps for missing weeks', () => {
  const rows = boardRows([report('W1', 'SHOW_RATE', 0.9), report('W3', 'SHOW_RATE', 0.95, { flag: 'ANOMALY' })], ['W1', 'W2', 'W3'], 'W3')
  expect(rows.get('SHOW_RATE')).toEqual({ value: 0.95, wow: 0.1, flag: true, usual: null, trend: [0.9, null, 0.95] })
  expect(boardRows([report('W1', 'SHOW_RATE', 0.9)], ['W1', 'W2'], 'W2').get('SHOW_RATE')).toMatchObject({ value: null, wow: null, flag: false })
})

it('builds the funnel only with an org row, and hides usual levels before the warm-up ends', () => {
  const org = { calls_out: 100, appointments_booked: 10, appointments_held: 9, conversions: 2 } as OrgWeekly
  const rates = [report('W2', 'CALL_TO_APPT', 0.1), report('W2', 'SHOW_RATE', 0.9), report('W2', 'APPT_CONV', 0.22)]
  expect(funnelFor(undefined, rates, 'W2')).toBeNull()
  const settled = funnelFor(org, rates, 'W2')!
  expect(settled.stages.map((s) => s.count)).toEqual([100, 10, 9, 2])
  expect(settled.steps.map((s) => s.usual)).toEqual([0.5, 0.5, 0.5])
  expect(funnelFor(org, rates, 'W2', false)!.steps.map((s) => s.usual)).toEqual([null, null, null])
  expect(funnelFor(org, [], 'W2')!.steps.map((s) => s.value)).toEqual([null, null, null])
})

it('leaves out a measure with no value, or none at all, once rows have loaded; the lead KPI comes first when it has one', () => {
  const row = (value: number | null): BoardRow => ({ value, wow: null, flag: false, trend: [value] })
  const codes = (rows: Map<KpiCode, BoardRow>) => boardGroups(rows).flatMap((g) => g.codes)
  // An export from before the lead KPI existed has no row for it: activities per advisor leads the board.
  expect(codes(new Map([['ACT_PER_ADV', row(16)], ['CALLS_OUT', row(7000)]]))).toEqual(['ACT_PER_ADV', 'CALLS_OUT'])
  // A first year of history has the row, but no value in any week.
  expect(codes(new Map([['PRTF_CONTACT_12M', row(null)], ['ACT_PER_ADV', row(16)]]))).toEqual(['ACT_PER_ADV'])
  expect(codes(new Map([['PRTF_CONTACT_12M', row(0.61)], ['ACT_PER_ADV', row(16)]]))).toEqual(['PRTF_CONTACT_12M', 'ACT_PER_ADV'])
  // Nothing loaded yet (an older week before the history arrives): every measure keeps its place.
  expect(codes(new Map())).toHaveLength(13)
})
