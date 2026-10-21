import { describe, expect, it } from 'vitest'
import { fiscalQuarterId, fiscalYear, quarterBefore, quarterLabel, quarterMonths, weekFiscalQuarterId, weekFiscalYear, weekSunday, yearEarlier } from './fiscal'

const day = (iso: string) => new Date(`${iso}T00:00:00Z`)

describe('the fiscal calendar (same cases as tests/test_fiscal.py)', () => {
  it.each([
    ['2025-10-31', 'FY25-Q4'],
    ['2025-11-01', 'FY26-Q1'],
    ['2026-01-31', 'FY26-Q1'],
    ['2026-02-01', 'FY26-Q2'],
    ['2026-07-31', 'FY26-Q3'],
    ['2026-10-31', 'FY26-Q4'],
  ])('%s is in %s', (iso, quarter) => {
    expect(fiscalQuarterId(day(iso))).toBe(quarter)
  })

  it('names the year for the calendar year it ends in', () => {
    expect(fiscalYear(day('2025-11-01'))).toBe(2026)
    expect(fiscalYear(day('2026-10-31'))).toBe(2026)
  })

  it('counts a week in the quarter holding its Sunday', () => {
    expect(weekSunday('2025-W44').toISOString().slice(0, 10)).toBe('2025-11-02')
    expect(weekFiscalQuarterId('2025-W44')).toBe('FY26-Q1')
    expect(weekFiscalQuarterId('2025-W43')).toBe('FY25-Q4')
    expect(weekFiscalYear('2026-W44')).toBe('FY27')
    // ISO years with 53 weeks, and week 1 starting in late December.
    expect(weekSunday('2026-W53').toISOString().slice(0, 10)).toBe('2027-01-03')
    expect(weekSunday('2025-W01').toISOString().slice(0, 10)).toBe('2025-01-05')
  })

  it('steps between quarters and labels them', () => {
    expect(quarterBefore('FY27-Q1')).toBe('FY26-Q4')
    expect(quarterBefore('FY26-Q3')).toBe('FY26-Q2')
    expect(yearEarlier('FY27-Q1')).toBe('FY26-Q1')
    expect(quarterLabel('FY26-Q1')).toBe('Q1 FY26')
    expect(quarterMonths('2025-11-01', '2026-01-31')).toBe('Nov 2025 – Jan 2026')
  })
})
