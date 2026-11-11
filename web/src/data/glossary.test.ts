import { describe, expect, it } from 'vitest'
import { CALENDAR_ADJUSTED, happened, verdict } from './glossary'

describe('happened', () => {
  it('says how the week compares with last week and with usual, judged by the good direction', () => {
    expect(happened({ code: 'ACT_PER_ADV', value: 15.7, wow: -0.118, usual: 17.37, flag: true, better: 'higher' })).toEqual([
      'Down 11.8% on last week.',
      '9.6% below usual (17.4): worse than a normal week.',
      'Flagged as an anomaly: after allowing for holidays and the February lift, further from the 13 weeks before than this area normally moves.',
    ])
  })

  it('gives the gap as a relative share, as the map and list do, and judges lower-is-better the right way round', () => {
    expect(happened({ code: 'NO_SHOW_RATE', value: 0.04, wow: -0.174, usual: 0.05, better: 'lower' })[1]).toBe('20.0% below usual (5.0%): better than a normal week.')
  })

  it('compares a rate with a 0% usual in points', () => {
    expect(happened({ code: 'QUAR_RATE', value: 0.012, usual: 0, better: 'lower' })).toEqual(['1.2 pts above usual (0.00%): worse than a normal week.'])
    expect(happened({ code: 'QUAR_RATE', value: 0, usual: 0, better: 'lower' })).toEqual(['Level with usual (0.00%).'])
  })

  it('states a small gap without calling it better or worse, so it never contradicts the colours', () => {
    expect(happened({ code: 'SHOW_RATE', value: 0.642, usual: 0.648, flag: true, better: 'higher' })).toEqual([
      '0.9% below usual (64.8%).',
      'Flagged as an anomaly: further from the 13 weeks before than this area normally moves.',
    ])
    expect(happened({ code: 'CALL_TO_APPT', value: 0.08201, usual: 0.082, better: 'higher' })).toEqual(['Level with usual (8.2%).'])
  })

  it('names the calendar allowance on the flag for exactly the four adjusted counts', () => {
    const adjusted = ['ACT_PER_ADV', 'CALLS_OUT', 'APPT_BOOKED', 'CLIENTS_CONTACTED'] as const
    for (const code of adjusted) {
      expect(happened({ code, value: 10, flag: true, better: 'higher' }).at(-1)).toMatch(/^Flagged as an anomaly: after allowing for holidays/)
    }
    expect([...CALENDAR_ADJUSTED].sort()).toEqual([...adjusted].sort())
    expect(happened({ code: 'SHOW_RATE', value: 0.5, flag: true, better: 'higher' }).at(-1)).not.toMatch(/holidays/)
  })

  it('says when there is no usual yet', () => {
    expect(happened({ code: 'CALLS_OUT', value: 10, usual: null, better: 'higher' })[0]).toMatch(/first 13 weeks/)
    expect(happened({ code: 'CALLS_OUT', value: null, better: 'higher' })).toEqual(['No value this week.'])
  })

  it('never judges a measure with no better direction', () => {
    expect(verdict(0.2, 'neither')).toBe('level')
    expect(happened({ code: 'AVG_MEET_MIN', value: 40, usual: 30, better: 'neither' })[0]).toBe('33.3% above usual (30.0).')
  })
})
