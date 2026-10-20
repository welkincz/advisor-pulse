import { expect, it } from 'vitest'
import type { RunSummary } from '../../data/generated/run_log'
import { formatDuration, runDuration } from './format'

it('formats milliseconds to hours', () => {
  expect(formatDuration(450)).toBe('450 ms')
  expect(formatDuration(41_700)).toBe('41.7 s')
  expect(formatDuration(63_000)).toBe('1 min 3 s')
  expect(formatDuration(119_600)).toBe('2 min 0 s')
  expect(formatDuration(7_190_000)).toBe('2 h 0 min')
  expect(formatDuration(10_618_000)).toBe('2 h 57 min')
})

it('measures the run still in progress at export to its last finished stage', () => {
  const run = {
    started_at: '2026-10-19T21:43:55Z', duration_ms: null,
    stages: [{ ended_at: '2026-10-20T00:41:00Z' }, { ended_at: '2026-10-20T00:45:16Z' }, { ended_at: null }],
  } as unknown as RunSummary
  expect(runDuration(run)).toEqual({ ms: 10_881_000, partial: true })
  expect(runDuration({ ...run, duration_ms: 5000 })).toEqual({ ms: 5000, partial: false })
  expect(runDuration({ ...run, stages: [] })).toBeNull()
})
