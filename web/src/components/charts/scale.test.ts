import { expect, it } from 'vitest'
import { annotatedWeek, domain, fenced, fitted, linePath, mixPoints, ticks } from './scale'

it('fits a value axis to the data with round ends, never crossing zero', () => {
  // The lead measure's quarters: 84.2% to 86.8% sit on 83% to 88%, not 0% to 100%.
  expect(fitted([0.868, 0.864, 0.842, null])).toEqual({ lo: 0.83, hi: 0.88, ticks: [0.83, 0.84, 0.85, 0.86, 0.87, 0.88] })
  expect(fitted([92.5, 101, 97.4])).toEqual({ lo: 90, hi: 105, ticks: [90, 95, 100, 105] })
  // A share near zero stops at zero, not a negative tick; an all-negative series stops at zero above.
  expect(fitted([0.01, 0.4])?.lo).toBe(0)
  expect(fitted([-3, -0.1])?.hi).toBe(0)
  expect(fitted([5])).toEqual({ lo: 4, hi: 6, ticks: [4, 4.5, 5, 5.5, 6] })
  expect(fitted([null, undefined])).toBeNull()
  // A share near 100% stops at 100%, not an impossible 110%.
  expect(fitted([0.9], 4, 0.15, 1)).toEqual({ lo: 0.7, hi: 1, ticks: [0.7, 0.8, 0.9, 1] })
  expect(fitted([0.97, 1], 4, 0.15, 1)?.hi).toBe(1)
})

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
