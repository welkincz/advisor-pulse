// @vitest-environment jsdom
import { act } from 'react'
import { type Root, createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { DataProvider } from '../../data'
import { fixtureData, fixtureFetch } from '../../data/testing/fixtures'
import { NarrativePanel } from './NarrativePanel'

declare global { var IS_REACT_ACT_ENVIRONMENT: boolean }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  container = document.createElement('div')
  root = createRoot(container)
})
afterEach(() => act(() => root.unmount()))

async function render(nodeId: string, fetcher = fixtureFetch(), week = '2026-W40') {
  await act(async () => root.render(
    <DataProvider data={fixtureData(fetcher)}>
      <NarrativePanel week={week} nodeId={nodeId} />
    </DataProvider>,
  ))
}

async function until(predicate: () => boolean) {
  for (let i = 0; i < 200 && !predicate(); i++) await act(() => new Promise((r) => setTimeout(r, 10)))
  expect(predicate()).toBe(true)
}

it('renders the fixture narrative and reveals facts per bullet', async () => {
  await render('ON')
  await until(() => container.textContent!.includes('Ontario: activities per advisor'))
  expect(container.textContent).toContain("AI-generated from this week's figures")
  expect(container.textContent).toContain('Eastern Ontario trails its peers')
  expect(container.textContent).toContain('Fewest activities per advisor under Ontario')
  const disclosures = container.querySelectorAll('details')
  expect(disclosures.length).toBe(5)
  expect(disclosures[0].open).toBe(false)
  await act(async () => disclosures[0].querySelector('summary')!.click())
  expect(disclosures[0].open).toBe(true)
  expect(disclosures[0].textContent).toContain('Outbound calls')
  expect(disclosures[0].textContent).toContain('59')
  expect(disclosures[0].textContent).toContain('Prior week: 61')
  await act(async () => disclosures[3].querySelector('summary')!.click())
  expect(disclosures[3].textContent).toContain('Rank 2 of 2')
})

it('labels fixture fallback as a template summary', async () => {
  await render('MTL')
  await until(() => container.textContent!.includes('Activities per advisor rose 40.0%'))
  expect(container.textContent).toContain('Template summary')
  expect(container.textContent).not.toContain('AI-generated from this week')
})

it('hides the panel when this node has no narrative', async () => {
  await render('NOPE')
  await until(() => !container.textContent!.includes('Loading weekly narrative'))
  expect(container.querySelector('section')).toBeNull()
})

it('explains when an older week has no published narrative', async () => {
  await render('ON', fixtureFetch(), '2026-W37')
  await until(() => container.textContent!.includes('No narrative was published for 2026-W37'))
  expect(container.querySelector('section[aria-labelledby="weekly-narrative-title"]')).not.toBeNull()
  expect(container.textContent).toContain('No narrative was published for 2026-W37')
})

it('shows a retryable notice when the narrative cannot load', async () => {
  await render('ON', fixtureFetch({
    'narratives/2026-W40.json': () => new Response('', { status: 503 }),
  }))
  await until(() => container.textContent!.includes('We could not load'))
  expect(container.textContent).toContain('Last weekly run:')
  expect(container.querySelector('button')?.textContent).toBe('Try again')
})

it.each(['value', 'prior_week_value', 'wow_pct', 'rank_in_parent'] as const)('marks a restated %s and shows its current figure', async (field) => {
  const data = fixtureData()
  const original = data.weeklyReportHistory.bind(data)
  data.weeklyReportHistory = async (node, weeks) => (await original(node, weeks)).map((r) =>
    r.node_id === 'ON' && r.kpi_code === 'CALLS_OUT' && r.iso_week_id === '2026-W40'
      ? { ...r, [field]: field === 'rank_in_parent' ? (r[field] === 1 ? 2 : 1) : (r[field] ?? 0) + 0.2 } : r)
  await act(async () => root.render(<DataProvider data={data}><NarrativePanel week="2026-W40" nodeId="ON" /></DataProvider>))
  await until(() => container.textContent!.includes('Late-arriving activity has since changed'))
  expect(container.querySelector('.narrative-restatement')?.textContent).toContain('1 of the figures')
  expect(container.querySelector('.narrative-bullets li[data-restated]')).not.toBeNull()
  expect(container.querySelector(`[data-field="${field}"]`)?.textContent).toBe({value: 'now 59.2', prior_week_value: 'now 61.2', wow_pct: 'now +16.7% WoW', rank_in_parent: 'now 2'}[field])
})

it('ignores changes beyond display precision, including cited child facts', async () => {
  const data = fixtureData()
  const original = data.weeklyReportHistory.bind(data)
  data.weeklyReportHistory = async (node, weeks) => (await original(node, weeks)).map((r) =>
    r.kpi_code === 'ACT_PER_ADV' ? { ...r, value: (r.value ?? 0) + 0.000001 } : r)
  await act(async () => root.render(<DataProvider data={data}><NarrativePanel week="2026-W40" nodeId="ON" /></DataProvider>))
  await until(() => container.textContent!.includes('Ontario: activities per advisor'))
  expect(container.querySelector('.narrative-restatement')).toBeNull()
})


it('marks a child watchlist fact once and exposes its current figure in both references', async () => {
  const data = fixtureData(), original = data.weeklyReportHistory.bind(data)
  data.weeklyReportHistory = async (node, weeks) => (await original(node, weeks)).map((r) => r.node_id === 'EON' && r.kpi_code === 'ACT_PER_ADV' && r.iso_week_id === '2026-W40' ? {...r, value: 11.3} : r)
  await act(async () => root.render(<DataProvider data={data}><NarrativePanel week="2026-W40" nodeId="ON" /></DataProvider>))
  await until(() => container.textContent!.includes('Late-arriving activity'))
  expect(container.querySelector('.narrative-restatement')?.getAttribute('data-restated-count')).toBe('1')
  expect(container.querySelector('.narrative-watchlist li[data-restated] [data-field="value"]')?.textContent).toBe('now 11.3')
})

it('withholds unchecked narrative text and retries failed current facts', async () => {
  const data = fixtureData(), original = data.weeklyReportHistory.bind(data)
  let fails = true
  data.weeklyReportHistory = async (...args) => { if (fails) { fails = false; throw new Error('unavailable') }; return original(...args) }
  await act(async () => root.render(<DataProvider data={data}><NarrativePanel week="2026-W40" nodeId="ON" /></DataProvider>))
  await until(() => container.textContent!.includes('We could not load the current cited figures'))
  expect(container.querySelector('.narrative-panel')).toBeNull()
  await act(async () => container.querySelector('button')!.click())
  await until(() => container.textContent!.includes('Ontario: activities per advisor'))
})
