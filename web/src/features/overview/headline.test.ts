import { expect, it } from 'vitest'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { extremeSince, nationalHeadline } from './headline'

const row = (week: number, value: number, wow: number | null, kpi_code: KpiCode = 'ACT_PER_ADV', flag = 'NONE') =>
  ({ iso_week_id: `2026-W${String(week).padStart(2, '0')}`, kpi_code, value, wow_pct: wow, flag }) as WeeklyReport

const steady = Array.from({ length: 12 }, (_, i) => row(i + 1, 17 + (i % 2) * 0.2, 0.01))

it('says how the lead measure moved and when it was last this low', () => {
  const history = [...steady.slice(0, 2), row(3, 15, -0.05), ...steady.slice(3, 11), row(12, 15.5, -0.076)]
  expect(extremeSince(history, '2026-W12')).toBe('the lowest since 2026-W03')
  expect(nationalHeadline(history, '2026-W12')!.lead).toBe('Activities per advisor fell 7.6% to 15.5, the lowest since 2026-W03.')
})

it('stays quiet about records that are only a few weeks old', () => {
  const history = [...steady.slice(0, 9), row(10, 15, -0.05), row(11, 17, 0.1), row(12, 15.5, -0.08)]
  expect(extremeSince(history, '2026-W12')).toBe('')
})

it('names the longest record when nothing in history matches', () => {
  const history = [...steady.slice(0, 11), row(12, 20, 0.15)]
  expect(extremeSince(history, '2026-W12')).toBe('the highest in 12 weeks on record')
})

it('adds the biggest anomaly among the other measures', () => {
  const history = [
    ...steady.slice(0, 11), row(12, 17.1, 0.001),
    row(12, 1581, -0.17, 'APPT_BOOKED', 'ANOMALY'), row(12, 0.075, -0.146, 'CALL_TO_APPT', 'ANOMALY'), row(12, 7375, -0.3, 'CALLS_OUT'),
  ]
  const headline = nationalHeadline(history, '2026-W12')!
  expect(headline.lead).toBe('Activities per advisor held steady at 17.1.')
  expect(headline.support).toBe('Appointments booked fell 17.0% to 1,581, outside its usual range, one of 2 measures flagged this week.')
})

it('says so when nothing else was unusual, and returns null for a missing week', () => {
  expect(nationalHeadline(steady, '2026-W05')!.support).toBe('Every other measure stayed within its usual range.')
  expect(nationalHeadline(steady, '2026-W40')).toBeNull()
})
