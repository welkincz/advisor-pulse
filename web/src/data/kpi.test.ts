import { describe, expect, it, test } from 'vitest'
import { defaultLead, formatKpi, leadFor } from './kpi'

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
