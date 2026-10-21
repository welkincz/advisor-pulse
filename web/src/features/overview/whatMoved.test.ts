// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import type { WeeklyReport } from '../../data/generated/weekly_report'
import { barShare, movedRows } from './WhatMoved'

// theme/tokens reads matchMedia at module load; jsdom has none.
vi.hoisted(() => {
  window.matchMedia ??= (() => ({ matches: false, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
})

const row = (node_id: string, value: number | null, usual: number | null): WeeklyReport =>
  ({ node_id, node_name: node_id, kpi_code: 'NO_SHOW_RATE', iso_week_id: '2026-W42', value, trailing_13w_avg: usual }) as WeeklyReport

describe('movedRows', () => {
  const rows = [row('ON', 0.05, 0.04), row('QC', 0.03, 0.04), row('BC', 0.04, null)]

  it('puts the best against usual first, judged by the measure’s direction', () => {
    // A no-show rate below usual is better, so Quebec leads and Ontario trails.
    expect(movedRows(rows, 'NO_SHOW_RATE', '2026-W42', 'lower', true).map((r) => r.id)).toEqual(['QC', 'ON', 'BC'])
    expect(movedRows(rows, 'NO_SHOW_RATE', '2026-W42', 'higher', true).map((r) => r.id)).toEqual(['ON', 'QC', 'BC'])
  })

  it('has no gap from usual before the week is settled, and puts those regions last', () => {
    const unsettled = movedRows(rows, 'NO_SHOW_RATE', '2026-W42', 'lower', false)
    expect(unsettled.every((r) => r.away === null && !r.settled)).toBe(true)
  })
})

describe('barShare', () => {
  it('grows right for better and left for worse, flipped when lower is better', () => {
    expect(barShare(0.1, 0.2, 'higher')).toBe(0.5)
    expect(barShare(0.1, 0.2, 'lower')).toBe(-0.5)
    expect(barShare(-0.4, 0.2, 'higher')).toBe(-1)
  })

  it('keeps the raw direction when neither way is better, and is empty with no usual', () => {
    expect(barShare(0.1, 0.2, 'neither')).toBe(0.5)
    expect(barShare(null, 0.2, 'higher')).toBe(0)
  })
})
