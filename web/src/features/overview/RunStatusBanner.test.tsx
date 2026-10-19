// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act } from 'react'
import { type Root, createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { DataProvider } from '../../data'
import type { Manifest } from '../../data/generated/manifest'
import type { RunLog } from '../../data/generated/run_log'
import { FIXTURES, fixtureData, fixtureFetch } from '../../data/testing/fixtures'
import { RunStatusBanner, failedLatestRun } from './RunStatusBanner'

declare global { var IS_REACT_ACT_ENVIRONMENT: boolean }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const manifest = JSON.parse(readFileSync(join(FIXTURES, 'manifest.json'), 'utf8')) as Manifest
const runLog = JSON.parse(readFileSync(join(FIXTURES, 'run_log.json'), 'utf8')) as RunLog

/** The fixture log plus a newer run for the next week with the given status. */
function withNewestRun(status: string, run_type = 'WEEKLY', started_at = '2026-10-12T11:00:00Z'): RunLog {
  const [latest] = runLog.runs
  const next = { ...latest, run_id: `${run_type.toLowerCase()}-2026-W41-1`, run_type, iso_week_id: '2026-W41', status, started_at, ended_at: started_at }
  return { ...runLog, runs: [next, ...runLog.runs].slice(0, 12) } as RunLog
}

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  container = document.createElement('div')
  root = createRoot(container)
})
afterEach(() => act(() => root.unmount()))

async function renderWith(log: RunLog | null) {
  const fetcher = fixtureFetch(log ? { 'run_log.json': () => new Response(JSON.stringify(log)) } : {})
  await act(async () => root.render(
    <DataProvider data={fixtureData(fetcher)}><MemoryRouter><RunStatusBanner manifest={manifest} /></MemoryRouter></DataProvider>,
  ))
  for (let i = 0; i < 50; i++) await act(() => new Promise((r) => setTimeout(r, 10)))
}

it('shows the failure and the still-visible older report week when the newest run FAILED', async () => {
  await renderWith(withNewestRun('FAILED'))
  const status = container.querySelector('[role="status"]')!
  expect(status.textContent).toContain('The last weekly run failed.')
  expect(status.textContent).toContain('The run for 2026-W41 did not finish')
  expect(status.textContent).toContain(`still shows the ${manifest.latest_week} report`)
  expect(container.querySelector('a')?.getAttribute('href')).toBe('/pipeline')
  expect(container.textContent).not.toMatch(/\blive\b|real-time/i)
})

it.each(['SUCCESS', 'WARN'])('shows no banner when the newest run is %s', async (status) => {
  await renderWith(withNewestRun(status))
  expect(container.querySelector('.run-status-banner')).toBeNull()
  expect(container.querySelector('[role="status"]')).not.toBeNull()
})

it('shows no banner for the committed fixtures, whose newest run is WARN', async () => {
  await renderWith(null)
  expect(container.querySelector('.run-status-banner')).toBeNull()
})

it('picks the newest run by start time, not by its position in the file', () => {
  const log = withNewestRun('FAILED')
  const reversed = { ...log, runs: [...log.runs].reverse() } as RunLog
  expect(failedLatestRun(reversed)?.iso_week_id).toBe('2026-W41')
  expect(failedLatestRun(runLog)).toBeNull()
})

it('ignores backfill and manual runs: only the newest weekly run decides', () => {
  expect(failedLatestRun(withNewestRun('FAILED', 'BACKFILL'))).toBeNull()
  const weeklyFailed = withNewestRun('FAILED')
  const thenManualOk = { ...weeklyFailed, runs: [{ ...weeklyFailed.runs[0], run_type: 'MANUAL', status: 'SUCCESS', started_at: '2026-10-13T09:00:00Z' }, ...weeklyFailed.runs] } as RunLog
  expect(failedLatestRun(thenManualOk)?.iso_week_id).toBe('2026-W41')
})

it('orders by instant, so a timestamp with an offset still sorts correctly', () => {
  const log = withNewestRun('FAILED', 'WEEKLY', '2026-10-12T07:00:00-04:00')
  expect(failedLatestRun({ ...log, runs: [...log.runs].reverse() } as RunLog)?.iso_week_id).toBe('2026-W41')
})
