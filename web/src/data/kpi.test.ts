import { expect, test } from 'vitest'
import { formatKpi } from './kpi'

test('averages keep a decimal; counts and rates read as before', () => {
  expect(formatKpi('ACT_PER_ADV', 16)).toBe('16.0')
  expect(formatKpi('AVG_MEET_MIN', 31.25)).toBe('31.3')
  expect(formatKpi('CALLS_OUT', 3067)).toBe('3,067')
  expect(formatKpi('COVERAGE_13W', 0.642)).toBe('64.2%')
  expect(formatKpi('CALLS_OUT', null)).toBe('–')
})
