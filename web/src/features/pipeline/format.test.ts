import { expect, it } from 'vitest'
import type { RunSummary } from '../../data/generated/run_log'
import { formatDuration, runDuration, runSentence } from './format'

it('formats milliseconds to hours', () => {
  expect(formatDuration(450)).toBe('450 ms')
  expect(formatDuration(41_700)).toBe('41.7 s')
  expect(formatDuration(63_000)).toBe('1 min 3 s')
  expect(formatDuration(119_600)).toBe('2 min 0 s')
  expect(formatDuration(999.6)).toBe('1.0 s')
  expect(formatDuration(59_960)).toBe('1 min 0 s')
  expect(formatDuration(3_599_600)).toBe('1 h 0 min')
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

it('names only a stage whose last attempt failed, and an in-flight run as running', () => {
  const attempt = (stage: string, attempt: number, status: string) => ({ stage, attempt, status, started_at: '2026-10-05T10:00:00Z', ended_at: '2026-10-05T10:00:01Z', duration_ms: 1000 })
  const run = {
    run_type: 'WEEKLY', iso_week_id: '2026-W39', status: 'SUCCESS', started_at: '2026-10-05T10:00:00Z', duration_ms: 60_000, checks: [],
    stages: [attempt('ingest', 1, 'FAILED'), attempt('ingest', 2, 'SUCCESS')],
  } as unknown as RunSummary
  expect(runSentence(run)).toBe('The weekly run for 2026-W39 succeeded in 1 min 0 s.')
  expect(runSentence({ ...run, status: 'RUNNING' })).toBe('The weekly run for 2026-W39 is still running.')
})
