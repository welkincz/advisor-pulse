import { describe, expect, it } from 'vitest'
import { TOO_WIDE, formatRange, rangeLine, wilson } from './interval'

describe('wilson', () => {
  it('matches a known value: 81 of 263 is 25.7% to 36.6%', () => {
    // Worked by hand from the closed form: centre 0.3107, half-width 0.0555.
    const range = wilson(81, 263)!
    expect(range.low).toBeCloseTo(0.2553, 4)
    expect(range.high).toBeCloseTo(0.3662, 4)
  })

  it('matches the Python evaluation in scripts/shrinkage_eval.py', () => {
    // 10 of 20, as scripts/shrinkage_eval.py's wilson() gives it, so the site and the ADR agree.
    const range = wilson(10, 20)!
    expect(range.low).toBeCloseTo(0.2993, 4)
    expect(range.high).toBeCloseTo(0.7007, 4)
  })

  it('has no interval with no clients', () => {
    expect(wilson(0, 0)).toBeNull()
    expect(wilson(3, 2)).toBeNull()
  })

  it('stays inside 0–1 at p = 0 and p = 1', () => {
    expect(wilson(0, 50)).toEqual({ low: 0, high: expect.closeTo(0.07135, 5) })
    expect(wilson(50, 50)).toEqual({ low: expect.closeTo(0.92865, 5), high: 1 })
  })

  it('always contains the rate and narrows as the book grows', () => {
    for (const [k, n] of [[1, 3], [58, 64], [1000, 1216], [140000, 151413]] as const) {
      const range = wilson(k, n)!
      expect(range.low).toBeLessThanOrEqual(k / n)
      expect(range.high).toBeGreaterThanOrEqual(k / n)
    }
    const small = wilson(84, 100)!
    const large = wilson(8400, 10000)!
    expect(large.high - large.low).toBeLessThan(small.high - small.low)
  })
})

describe('rangeLine', () => {
  it('reads "likely" with the book size', () => {
    expect(formatRange({ low: 0.8312, high: 0.8534 })).toBe('83.1–85.3%')
    expect(rangeLine({ contacted: 1024, clients: 1216 })).toBe('Likely 82.1–86.2%, from 1,216 clients.')
  })

  it('says plainly when a book is too small to read', () => {
    const range = wilson(15, 20)!
    expect(range.high - range.low).toBeGreaterThan(TOO_WIDE)
    expect(rangeLine({ contacted: 15, clients: 20 })).toBe('Too few clients (20) to read: likely 53.1–88.8%.')
  })

  it('says nothing without clients', () => {
    expect(rangeLine({ contacted: 0, clients: 0 })).toBeNull()
    expect(rangeLine(null)).toBeNull()
  })
})
