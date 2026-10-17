// @vitest-environment jsdom
import { act, useState } from 'react'
import { type Root, createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { DataNotice } from './DataNotice'
import { DataProvider, useNarrative, useOrgWeekly, useWeeklyReport } from './hooks'
import type { PulseData } from './store'
import { fixtureData, fixtureFetch } from './testing/fixtures'

declare global { var IS_REACT_ACT_ENVIRONMENT: boolean }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  container = document.createElement('div')
  root = createRoot(container)
})
afterEach(() => act(() => root.unmount()))

async function render(data: PulseData, ui: React.ReactNode) {
  await act(async () => root.render(<DataProvider data={data}>{ui}</DataProvider>))
}

async function until(predicate: () => boolean) {
  for (let i = 0; i < 200 && !predicate(); i++) await act(() => new Promise((r) => setTimeout(r, 10)))
  expect(predicate()).toBe(true)
}

function Advisors({ nodeId }: { nodeId: string }) {
  const result = useOrgWeekly(nodeId, ['2026-W39', '2026-W40'])
  if (result.status !== 'ready') return <p>{result.status}</p>
  return <p>{result.data.map((r) => `${r.iso_week_id}:${r.active_advisors}`).join(' ')}</p>
}

it('useOrgWeekly goes from loading to typed rows', async () => {
  await render(fixtureData(), <Advisors nodeId="ON" />)
  expect(container.textContent).toBe('loading')
  await until(() => container.textContent!.startsWith('2026-W39:'))
  expect(container.textContent).toMatch(/^2026-W39:\d+ 2026-W40:\d+$/)
})

it('reloads when the node changes and never shows the previous node', async () => {
  function Switcher() {
    const [node, setNode] = useState('ON')
    return <><button onClick={() => setNode('QC')}>QC</button><Advisors nodeId={node} /></>
  }
  await render(fixtureData(), <Switcher />)
  await until(() => container.textContent!.includes('2026-W40:'))
  const on = container.textContent
  await act(async () => container.querySelector('button')!.click())
  expect(container.textContent).toBe('QCloading')
  await until(() => container.textContent!.includes('2026-W40:'))
  expect(container.textContent).not.toBe(on)
})

it('reports empty for a node with no rows', async () => {
  function Report() {
    return <p>{useWeeklyReport('2026-W40', { parentId: 'NOPE' }).status}</p>
  }
  await render(fixtureData(), <Report />)
  await until(() => container.textContent === 'empty')
})

it('useNarrative returns the node narrative', async () => {
  function Headline() {
    const result = useNarrative('2026-W40', 'QC')
    return <p>{result.status === 'ready' ? result.data.headline : result.status}</p>
  }
  await render(fixtureData(), <Headline />)
  await until(() => container.textContent!.startsWith('Quebec'))
})

it('a failed fetch shows a calm notice with the last run time, and retry recovers', async () => {
  let down = true
  const fetcher = fixtureFetch({
    'org_weekly.parquet': async () => (down ? new Response('', { status: 503 }) : fixtureFetch()('/data/org_weekly.parquet')),
  })
  function Section() {
    const result = useOrgWeekly('ON', ['2026-W40'])
    if (result.status === 'error') return <DataNotice what="Ontario's trend" onRetry={result.retry} />
    return <p>{result.status}</p>
  }
  await render(fixtureData(fetcher), <Section />)
  await until(() => container.textContent!.includes('Last weekly run'))
  expect(container.textContent).toContain("We could not load Ontario's trend just now.")
  expect(container.textContent).toContain('Last weekly run: Oct 5, 2026')
  down = false
  await act(async () => container.querySelector('button')!.click())
  await until(() => container.textContent === 'ready')
})
