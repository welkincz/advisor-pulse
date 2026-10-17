// @vitest-environment jsdom
import { act } from 'react'
import { type Root, createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DataProvider } from '../../data'
import { fixtureData } from '../../data/testing/fixtures'
import { LeaderTable, OrgLeaderboard, VIRTUAL_AFTER } from './Leaderboard'
import type { LeaderRow } from './rows'

// Chart (imported through the primitives index) reads matchMedia at module load; jsdom has none.
vi.hoisted(() => {
  window.matchMedia ??= (() => ({ matches: false, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
})

declare global { var IS_REACT_ACT_ENVIRONMENT: boolean }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  container = document.createElement('div')
  root = createRoot(container)
})
afterEach(() => act(() => root.unmount()))

async function until(predicate: () => boolean) {
  for (let i = 0; i < 200 && !predicate(); i++) await act(() => new Promise((r) => setTimeout(r, 10)))
  expect(predicate()).toBe(true)
}

it('ranks the fixture regions under Canada with table semantics and drill links', async () => {
  await act(async () => root.render(<MemoryRouter><DataProvider data={fixtureData()}>
    <OrgLeaderboard weeks={['2026-W37', '2026-W38', '2026-W39', '2026-W40']} parentId="CA" parentName="Canada" childHref={(id) => `/r/${id}`} />
  </DataProvider></MemoryRouter>))
  await until(() => container.querySelector('table') !== null)
  const table = container.querySelector('table')!
  expect(table.querySelector('caption')?.textContent).toBe('Activities per advisor under Canada, week 2026-W40. Trend covers the last 8 weeks.')
  expect([...table.querySelectorAll('thead th')].every((th) => th.getAttribute('scope') === 'col')).toBe(true)
  const names = [...table.querySelectorAll('tbody th[scope="row"] a')].map((a) => a.getAttribute('href'))
  expect(names.sort()).toEqual(['/r/ON', '/r/QC'])
  expect(table.getAttribute('aria-rowcount')).toBe('3')
  expect(table.querySelectorAll('tbody tr td:first-child')[0]?.textContent).toBe('1')
})

it('renders only the rows in view above the virtualization threshold', async () => {
  const rows: LeaderRow[] = Array.from({ length: VIRTUAL_AFTER + 50 }, (_, i) => ({
    id: `ADV-${i}`, name: `ADV-${i}`, value: 200 - i, rank: i + 1, priorRank: i + 1, trend: [1, 2],
  }))
  await act(async () => root.render(<MemoryRouter><LeaderTable rows={rows} code="CALLS_OUT" caption="Calls" /></MemoryRouter>))
  const table = container.querySelector('table')!
  const rendered = table.querySelectorAll('tbody tr:not([aria-hidden])')
  expect(rendered.length).toBeLessThan(40)
  expect(table.getAttribute('aria-rowcount')).toBe(String(rows.length + 1))
  expect(rendered[0]?.getAttribute('aria-rowindex')).toBe('2')
  const scroller = container.querySelector('[role="region"]') as HTMLDivElement
  expect(scroller.tabIndex).toBe(0)
  await act(async () => {
    scroller.scrollTop = 44 * 100
    scroller.dispatchEvent(new Event('scroll', { bubbles: true }))
  })
  const after = [...table.querySelectorAll('tbody tr:not([aria-hidden])')]
  expect(after.some((row) => row.textContent?.includes('ADV-100'))).toBe(true)
  expect(after.some((row) => row.textContent?.includes('ADV-0'))).toBe(false)
})

it('renders every row at or below the threshold', async () => {
  const rows: LeaderRow[] = Array.from({ length: 12 }, (_, i) => ({ id: `B${i}`, name: `B${i}`, value: i, rank: 12 - i, priorRank: null, trend: [] }))
  await act(async () => root.render(<MemoryRouter><LeaderTable rows={rows} code="CALLS_OUT" caption="Calls" /></MemoryRouter>))
  expect(container.querySelectorAll('tbody tr')).toHaveLength(12)
  expect(container.querySelector('[role="region"]')).toBeNull()
})
