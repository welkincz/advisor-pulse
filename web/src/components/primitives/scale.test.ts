import { expect, it } from 'vitest'
import { fenced } from './scale'

it('handles empty, all-null and single-value series', () => {
  expect(fenced([])).toBeNull()
  expect(fenced([null, null])).toBeNull()
  expect(fenced([0.4])).toEqual([0.4, 0.4])
})

it('keeps every value when none is far out, and drops the ones beyond the fences', () => {
  expect(fenced([1, 2, 3, 4, 5])).toEqual([1, 5])
  expect(fenced([10, 10.1, 10.2, 10.3, 10.4, 10.5, 0])).toEqual([10, 10.5])
})
