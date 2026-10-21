import { describe, expect, it } from 'vitest'
import type { OrgQuarterly } from '../../data/generated/org_quarterly'
import { change, quarterSeries, toDate } from './quarters'

function row(id: string, overrides: Partial<OrgQuarterly> = {}): OrgQuarterly {
  return {
    fiscal_quarter_id: id, fiscal_year: 2000 + Number(id.slice(2, 4)), fiscal_quarter: Number(id.slice(-1)),
    quarter_start: '2025-11-01', quarter_end: '2026-01-31', first_week: '2025-W44', last_week: '2026-W05',
    weeks_reported: 13, weeks_in_quarter: 13, is_complete: true, level: 'NATIONAL', node_id: 'CA', node_name: 'Canada', parent_id: null,
    advisor_weeks: 1300, activities_completed: 13000, calls_out: 2600, calls_in: 0, appointments_booked: 260, booked_from_call: 130,
    appointments_held: 200, no_shows: 20, conversions: 50, unique_clients_contacted: 4000, book_size: 10000, clients_covered_13w: 6000,
    coverage_rate_13w: 0.6, avg_meeting_duration_min: 30, activities_per_advisor: 10, show_rate: 0.9, conversion_rate: 0.25, call_to_appt_rate: 0.05,
    ...overrides,
  }
}

describe('fiscal quarter measures', () => {
  const rows = [
    row('FY25-Q4'),
    row('FY26-Q3', { activities_per_advisor: 11, unique_clients_contacted: 5000 }),
    row('FY26-Q4', { weeks_reported: 6, is_complete: false, calls_out: 1500, activities_per_advisor: 12, unique_clients_contacted: 2500 }),
    row('FY26-Q4', { node_id: 'ON', level: 'REGION', parent_id: 'CA' }),
  ]

  it('averages flows per week, so a quarter to date compares with a whole one', () => {
    const calls = quarterSeries(rows, 'CA', 'CALLS_OUT')
    expect(calls.map((p) => p.id)).toEqual(['FY25-Q4', 'FY26-Q3', 'FY26-Q4'])
    expect(calls.map((p) => p.value)).toEqual([200, 200, 250])
    expect(change(calls, 'FY26-Q4', 'CALLS_OUT', 'qoq')).toEqual({ value: 0.25 })
    expect(change(calls, 'FY26-Q4', 'CALLS_OUT', 'yoy')).toEqual({ value: 0.25 })
  })

  it('compares rates directly and rebuilds the no-show rate from its parts', () => {
    const rate = quarterSeries(rows, 'CA', 'ACT_PER_ADV')
    expect((change(rate, 'FY26-Q4', 'ACT_PER_ADV', 'qoq') as { value: number }).value).toBeCloseTo(12 / 11 - 1)
    expect(quarterSeries(rows, 'CA', 'NO_SHOW_RATE')[0]!.value).toBeCloseTo(20 / 220)
  })

  it('holds distinct clients until the quarter closes', () => {
    const clients = quarterSeries(rows, 'CA', 'CLIENTS_CONTACTED')
    expect(change(clients, 'FY26-Q4', 'CLIENTS_CONTACTED', 'qoq')).toEqual({ value: null, reason: 'to-date' })
    expect((change(clients, 'FY26-Q3', 'CLIENTS_CONTACTED', 'qoq') as { value: number | null }).value).toBeNull()
  })

  it('says when there is no quarter to compare with, and how far a quarter has run', () => {
    const calls = quarterSeries(rows, 'CA', 'CALLS_OUT')
    expect(change(calls, 'FY25-Q4', 'CALLS_OUT', 'qoq')).toEqual({ value: null, reason: 'no-quarter' })
    expect(toDate(calls.at(-1)!)).toBe('6 of 13 weeks')
    expect(toDate(calls[0]!)).toBeNull()
    expect(quarterSeries(rows, 'CA', 'LATE_RATE')).toEqual([])
  })
})
