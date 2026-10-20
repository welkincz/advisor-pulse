import { expect, it } from 'vitest'
import { isoWeekMonday, weekSpan } from './week'

it('finds the Monday of an ISO week, including week 1 that starts in December', () => {
  expect(isoWeekMonday('2026-W42')!.toISOString().slice(0, 10)).toBe('2026-10-12')
  expect(isoWeekMonday('2026-W01')!.toISOString().slice(0, 10)).toBe('2025-12-29')
  expect(isoWeekMonday('2020-W53')!.toISOString().slice(0, 10)).toBe('2020-12-28')
  expect(isoWeekMonday('2026-42')).toBeNull()
})

it('writes the span the way a reader says it', () => {
  expect(weekSpan('2026-W42')).toBe('October 12 to 18, 2026')
  expect(weekSpan('2026-W40')).toBe('September 28 to October 4, 2026')
  expect(weekSpan('2026-W01')).toBe('December 29, 2025 to January 4, 2026')
})
