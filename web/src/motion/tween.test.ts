import { expect, it } from 'vitest'
import { cubicBezier, standardEase } from './tween'

it('the standard ease starts at 0, ends at 1 and never runs backwards', () => {
  expect(standardEase(0)).toBe(0)
  expect(standardEase(1)).toBe(1)
  let last = 0
  for (let t = 0.05; t < 1; t += 0.05) {
    const value = standardEase(t)
    expect(value).toBeGreaterThanOrEqual(last)
    last = value
  }
  // Decelerating: most of the change happens early.
  expect(standardEase(0.3)).toBeGreaterThan(0.6)
})

it('a linear bezier is the identity', () => {
  const linear = cubicBezier(0.25, 0.25, 0.75, 0.75)
  for (const t of [0.1, 0.5, 0.9]) expect(linear(t)).toBeCloseTo(t, 4)
})
