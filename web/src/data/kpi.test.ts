import { describe, expect, it, test } from 'vitest'
import { defaultLead, formatChange, formatKpi, formatWow, leadFor } from './kpi'

test('batch data-quality rates keep two decimals, so a small rate never reads as 0.0%', () => {
  expect(formatKpi('QUAR_RATE', 0.0003)).toBe('0.03%')
  expect(formatKpi('LATE_RATE', 0.0156)).toBe('1.56%')
})

test('a change is written one way: signed, one decimal, a real minus, ±0.0% when level', () => {
  expect(formatChange(0.146)).toBe('+14.6%')
  expect(formatChange(-0.071)).toBe('−7.1%')
  // Under half a tenth of a point the table, the card and the delta all call it level.
  expect(formatChange(0.0003)).toBe('±0.0%')
  // At the boundary the sign and the rounding agree: half a tenth of a point is +0.1%.
  expect(formatChange(0.0005)).toBe('+0.1%')
  expect(formatChange(-0.0005)).toBe('−0.1%')
  expect(formatWow(0.0003)).toBe('±0.0% WoW')
  expect(formatWow(null)).toBe('no prior week')
})

test('averages keep a decimal; counts and rates read as before', () => {
  expect(formatKpi('ACT_PER_ADV', 16)).toBe('16.0')
  expect(formatKpi('AVG_MEET_MIN', 31.25)).toBe('31.3')
  expect(formatKpi('CALLS_OUT', 3067)).toBe('3,067')
  expect(formatKpi('SHOW_RATE', 0.642)).toBe('64.2%')
  expect(formatKpi('CALLS_OUT', null)).toBe('–')
})

describe('the lead KPI', () => {
  it('leads once the latest summary has a value for it, and falls back to activities per advisor before', () => {
    expect(defaultLead([{ kpi_code: 'PRTF_CONTACT_12M', value: 0.84 }, { kpi_code: 'ACT_PER_ADV', value: 16 }])).toBe('PRTF_CONTACT_12M')
    expect(defaultLead([{ kpi_code: 'PRTF_CONTACT_12M', value: null }, { kpi_code: 'ACT_PER_ADV', value: 16 }])).toBe('ACT_PER_ADV')
    expect(defaultLead([])).toBe('ACT_PER_ADV')
  })

  it('picks the headline per week: a week without 12 months of history leads with activities', () => {
    const history = [
      { kpi_code: 'PRTF_CONTACT_12M' as const, iso_week_id: '2025-W40', value: null },
      { kpi_code: 'PRTF_CONTACT_12M' as const, iso_week_id: '2025-W41', value: 0.84 },
    ]
    expect(leadFor(history, '2025-W40')).toBe('ACT_PER_ADV')
    expect(leadFor(history, '2025-W41')).toBe('PRTF_CONTACT_12M')
    expect(formatKpi('PRTF_CONTACT_12M', 0.8376)).toBe('83.8%')
  })
})
