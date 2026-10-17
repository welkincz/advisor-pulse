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

async function render(nodeId: string, fetcher = fixtureFetch()) {
  await act(async () => root.render(
    <DataProvider data={fixtureData(fetcher)}>
      <NarrativePanel week="2026-W40" nodeId={nodeId} />
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
  expect(container.textContent).toContain('GTA trails its peers')
  expect(container.textContent).toContain('Lowest 13-week coverage under Ontario')
  const disclosures = container.querySelectorAll('details')
  expect(disclosures.length).toBe(4)
  expect(disclosures[0].open).toBe(false)
  await act(async () => disclosures[0].querySelector('summary')!.click())
  expect(disclosures[0].open).toBe(true)
  expect(disclosures[0].textContent).toContain('Outbound calls')
  expect(disclosures[0].textContent).toContain('59')
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

it('shows a retryable notice when the narrative cannot load', async () => {
  await render('ON', fixtureFetch({
    'narratives/2026-W40.json': () => new Response('', { status: 503 }),
  }))
  await until(() => container.textContent!.includes('We could not load'))
  expect(container.textContent).toContain('Last weekly run:')
  expect(container.querySelector('button')?.textContent).toBe('Try again')
})
