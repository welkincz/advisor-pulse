import { expect, it } from 'vitest'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { extremeSince, measuresSentence, moveSentence, nodeHeadline, weekHeadline } from './headline'

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

it('writes one move sentence for every page, and none without a value', () => {
  expect(moveSentence('PRTF_CONTACT_12M', 0.842, 0.001)).toBe('Portfolio contacted (12 months) held steady at 84.2%.')
  expect(moveSentence('PRTF_CONTACT_12M', 0.842, -0.012)).toBe('Portfolio contacted (12 months) fell 1.2% to 84.2%.')
  expect(moveSentence('PRTF_CONTACT_12M', 0.842, null)).toBe('Portfolio contacted (12 months) was 84.2%.')
  expect(moveSentence('ACT_PER_ADV', 16, 0.1, 'Activities completed')).toBe('Activities completed rose 10.0% to 16.0.')
  expect(moveSentence('PRTF_CONTACT_12M', null, 0.01)).toBeNull()
  expect(moveSentence('PRTF_CONTACT_12M', undefined, undefined)).toBeNull()
})

it('opens a node with the lead KPI, and with activities in a week the lead has no value', () => {
  const history = [
    row(11, 0.84, null, 'PRTF_CONTACT_12M'), row(12, 0.842, 0.002, 'PRTF_CONTACT_12M'),
    row(11, 17, null), row(12, 15.5, -0.102),
  ]
  // The overview and a drill page ask the same question and get the same sentence.
  const headline = nodeHeadline(history, '2026-W12', 'PRTF_CONTACT_12M')!
  expect(headline.lead).toBe('Portfolio contacted (12 months) held steady at 84.2%.')
  expect(headline.support).toBe('Every other measure stayed within its usual range.')
  const early = [row(12, null, null, 'PRTF_CONTACT_12M'), row(12, 15.5, -0.102)]
  expect(nodeHeadline(early, '2026-W12', 'PRTF_CONTACT_12M')!.lead).toBe('Activities per advisor fell 10.2% to 15.5.')
  expect(nodeHeadline([], '2026-W12', 'PRTF_CONTACT_12M')).toBeNull()
  expect(nodeHeadline([row(12, null, null, 'PRTF_CONTACT_12M'), row(12, null, null)], '2026-W12', 'PRTF_CONTACT_12M')).toBeNull()
})

it('opens an advisor page from their tiles, falling back to activities completed', () => {
  const label = (code: KpiCode) => (code === 'ACT_PER_ADV' ? 'Activities completed' : 'Portfolio contacted (12 months)')
  const tiles = [{ code: 'PRTF_CONTACT_12M' as const, value: 0.9, wow: 0.0111 }, { code: 'ACT_PER_ADV' as const, value: 14, wow: -0.125 }]
  expect(measuresSentence(tiles, 'PRTF_CONTACT_12M', label)).toBe('Portfolio contacted (12 months) rose 1.1% to 90.0%.')
  const noPortfolio = [{ ...tiles[0]!, value: null, wow: null }, tiles[1]!]
  expect(measuresSentence(noPortfolio, 'PRTF_CONTACT_12M', label)).toBe('Activities completed fell 12.5% to 14.0.')
  expect(measuresSentence([], 'PRTF_CONTACT_12M')).toBeNull()
})
