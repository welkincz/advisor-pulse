import { expect, it } from 'vitest'
import { annotatedWeek, domain, fenced, linePath, mixPoints, ticks } from './scale'

it('handles empty, all-null and single-value series', () => {
  expect(fenced([])).toBeNull()
  expect(fenced([null, null])).toBeNull()
  expect(fenced([0.4])).toEqual([0.4, 0.4])
})

it('keeps every value when none is far out, and drops the ones beyond the fences', () => {
  expect(fenced([1, 2, 3, 4, 5])).toEqual([1, 5])
  expect(fenced([10, 10.1, 10.2, 10.3, 10.4, 10.5, 0])).toEqual([10, 10.5])
})

it('picks round ticks across the range', () => {
  expect(ticks(0, 100, 4)).toEqual([0, 25, 50, 75, 100])
  expect(ticks(15.2, 18.9, 4)).toEqual([16, 17, 18])
  expect(ticks(5, 5)).toEqual([5])
  expect(ticks(Number.NaN, 1)).toEqual([])
})

it('pads the domain and ignores missing values', () => {
  expect(domain([null, 10, 20], 0.1)).toEqual([9, 21])
  expect(domain([null, undefined])).toBeNull()
  expect(domain([4], 0.5)).toEqual([2, 6])
})

it('breaks lines at gaps and morphs only points present at the end', () => {
  expect(linePath([[0, 0], [1, 1], null, [3, 3]])).toBe('M0.0,0.0L1.0,1.0M3.0,3.0')
  expect(mixPoints([[0, 0], null], [[10, 10], [5, 5]], 0.5)).toEqual([[5, 5], [5, 5]])
  expect(mixPoints([[0, 0]], [null], 0.5)).toEqual([null])
})

it('circles the selected week when flagged, else the latest flagged week with a value', () => {
  const values = [1, 2, 3, null, 5]
  expect(annotatedWeek([false, true, false, false, true], values, 1)).toBe(1)
  expect(annotatedWeek([false, true, false, false, true], values, 2)).toBe(4)
  expect(annotatedWeek([false, true, false, true, false], values, -1)).toBe(1)
  expect(annotatedWeek([false, false, false, false, false], values, 0)).toBeNull()
  expect(annotatedWeek(undefined, values, 0)).toBeNull()
  // A flagged week with no value cannot be circled: fall back to the latest one that has a value.
  expect(annotatedWeek([true, false, false, true, false], values, 3)).toBe(0)
})
