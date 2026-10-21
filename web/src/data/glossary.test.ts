import { describe, expect, it } from 'vitest'
import { happened, verdict } from './glossary'

describe('happened', () => {
  it('says how the week compares with last week and with usual, judged by the good direction', () => {
    expect(happened({ code: 'ACT_PER_ADV', value: 15.7, wow: -0.118, usual: 17.37, flag: true, better: 'higher' })).toEqual([
      'Down 11.8% on last week.',
      '9.6% below usual (17.4): worse than a normal week.',
      'Flagged as an anomaly: worth a closer look.',
    ])
  })

  it('reads rates in percentage points and lower-is-better measures the right way round', () => {
    expect(happened({ code: 'NO_SHOW_RATE', value: 0.04, wow: -0.174, usual: 0.05, better: 'lower' })[1]).toBe('1.0 pts below usual (5.0%): better than a normal week.')
  })

  it('compares a rate with a 0% usual in points', () => {
    expect(happened({ code: 'QUAR_RATE', value: 0.012, usual: 0, better: 'lower' })).toEqual(['1.2 pts above usual (0.0%): worse than a normal week.'])
    expect(happened({ code: 'QUAR_RATE', value: 0, usual: 0, better: 'lower' })).toEqual(['About usual (0.0%).'])
  })

  it('calls a small gap about usual, and says when there is no usual yet', () => {
    expect(happened({ code: 'CALL_TO_APPT', value: 0.0821, usual: 0.082, better: 'higher' })).toEqual(['About usual (8.2%).'])
    expect(happened({ code: 'CALLS_OUT', value: 10, usual: null, better: 'higher' })[0]).toMatch(/first 13 weeks/)
    expect(happened({ code: 'CALLS_OUT', value: null, better: 'higher' })).toEqual(['No value this week.'])
  })

  it('never judges a measure with no better direction', () => {
    expect(verdict(0.2, 'neither')).toBe('level')
    expect(happened({ code: 'AVG_MEET_MIN', value: 40, usual: 30, better: 'neither' })[0]).toBe('33.3% above usual (30.0).')
  })
})
