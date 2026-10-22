import { expect, it } from 'vitest'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { extremeSince, weekHeadline } from './headline'

const row = (week: number, value: number | null, wow: number | null, kpi_code: KpiCode = 'ACT_PER_ADV', flag = 'NONE') =>
  ({ iso_week_id: `2026-W${String(week).padStart(2, '0')}`, kpi_code, value, wow_pct: wow, flag }) as WeeklyReport

const steady = Array.from({ length: 12 }, (_, i) => row(i + 1, 17 + (i % 2) * 0.2, 0.01))

it('says how the lead measure moved and when it was last this low', () => {
  const history = [...steady.slice(0, 2), row(3, 15, -0.05), ...steady.slice(3, 11), row(12, 15.5, -0.076)]
  expect(extremeSince(history, '2026-W12')).toBe('the lowest since 2026-W03')
  const headline = weekHeadline(history, '2026-W12')!
  expect(headline.lead).toBe('Activities per advisor fell 7.6% to 15.5, the lowest since 2026-W03.')
  // The overview's title is the move alone; the record opens the line under it.
  expect(headline.title).toBe('Activities per advisor fell 7.6% to 15.5.')
  expect(headline.record).toBe('The lowest since 2026-W03.')
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
  const headline = weekHeadline(history, '2026-W12')!
  expect(headline.lead).toBe('Activities per advisor held steady at 17.1.')
  expect(headline.title).toBe(headline.lead)
  expect(headline.record).toBe('')
  expect(headline.support).toBe('Appointments booked fell 17.0% to 1,581, outside its usual range, one of 2 measures flagged this week.')
})

it('says so when nothing else was unusual, and returns null for a missing week', () => {
  expect(weekHeadline(steady, '2026-W05')!.support).toBe('Every other measure stayed within its usual range.')
  expect(weekHeadline(steady, '2026-W40')).toBeNull()
})

it('leads with portfolio contacted when asked to, and its title fits the move alone', () => {
  const portfolio = Array.from({ length: 12 }, (_, i) => row(i + 1, 0.6 + i * 0.001, 0.002, 'PRTF_CONTACT_12M'))
  const headline = weekHeadline(portfolio, '2026-W12', 'PRTF_CONTACT_12M')!
  expect(headline.title).toBe('Portfolio contacted (12 months) held steady at 61.1%.')
  expect(headline.record).toBe('')
  // A week without 12 months of history has no value to lead with: no sentence, so the page falls back.
  expect(weekHeadline([row(12, null, null, 'PRTF_CONTACT_12M')], '2026-W12', 'PRTF_CONTACT_12M')).toBeNull()
})
