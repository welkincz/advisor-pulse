import { expect, it } from 'vitest'
import type { WeeklyReport } from './generated/weekly_report'
import { deviationReach, usualStep, versusUsual } from './usual'

const row = (value: number | null, trailing_13w_avg: number | null) => ({ kpi_code: 'SHOW_RATE', value, trailing_13w_avg }) as WeeklyReport

it('measures a week against its own 13-week average', () => {
  expect(versusUsual(row(11, 10))).toBeCloseTo(0.1)
  expect(versusUsual(row(11, null))).toBeNull()
  expect(versusUsual(row(null, 10))).toBeNull()
  expect(versusUsual(row(5, 0))).toBeNull()
})

it('sizes the scale from typical weeks and steps better or worse by the KPI direction', () => {
  const reach = deviationReach([row(10.2, 10), row(9.8, 10), row(10.1, 10), row(9.9, 10), row(20, 10)], 'SHOW_RATE')
  expect(reach).toBeCloseTo(0.02)
  expect(usualStep(0, reach, false)).toBe(3)
  expect(usualStep(0.02, reach, false)).toBe(6)
  expect(usualStep(0.02, reach, true)).toBe(0)
  expect(usualStep(0.5, reach, false)).toBe(6)
  expect(usualStep(null, reach, false)).toBeNull()
})
