// @vitest-environment jsdom
import { act } from 'react'
import { type Root, createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { KpiCode } from '../../data/generated/weekly_report'
import { type BoardRow, KpiBoard, cardLines } from './KpiBoard'

declare global { var IS_REACT_ACT_ENVIRONMENT: boolean }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

// theme/tokens (reached through the primitives index) reads matchMedia at module load; jsdom has none.
vi.hoisted(() => {
  window.matchMedia ??= (() => ({ matches: false, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
})

const lead: BoardRow = { value: 0.8421, wow: 0.001, flag: false, trend: [0.84, 0.8421] }

it('opens the lead KPI card with its likely range, and only the lead KPI', () => {
  const lines = cardLines('PRTF_CONTACT_12M', lead, { contacted: 1024, clients: 1216 }, 'higher')
  expect(lines[0]).toBe('Likely 82.1–86.2%, from 1,216 clients.')
  expect(lines.length).toBeGreaterThan(1)
  expect(cardLines('SHOW_RATE', lead, { contacted: 1024, clients: 1216 }, 'higher')[0]).not.toMatch(/Likely/)
})

it('says a small book is too small to read, and says nothing before the counts load', () => {
  expect(cardLines('PRTF_CONTACT_12M', lead, { contacted: 15, clients: 20 }, 'higher')[0]).toBe('Too few clients (20) to read: likely 53.1–88.8%.')
  expect(cardLines('PRTF_CONTACT_12M', lead, null, 'higher').join(' ')).not.toMatch(/Likely|Too few/)
  // No rate this week (before 12 months of history): no range either.
  expect(cardLines('PRTF_CONTACT_12M', { ...lead, value: null }, { contacted: 0, clients: 10 }, 'higher')).toEqual(['No value this week.'])
})

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  vi.useFakeTimers()
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.useRealTimers()
})

it('shows the range in the hover card on the board', () => {
  const rows = new Map<KpiCode, BoardRow>([['PRTF_CONTACT_12M', lead]])
  act(() => root.render(<KpiBoard rows={rows} selected="PRTF_CONTACT_12M" onSelect={() => {}} counts={{ contacted: 1024, clients: 1216 }} />))
  const trigger = host.querySelector('[data-kpi="PRTF_CONTACT_12M"] .explain')!
  act(() => { trigger.dispatchEvent(new PointerEvent('pointerover', { bubbles: true, pointerType: 'mouse' })) })
  act(() => { vi.advanceTimersByTime(200) })
  const card = document.querySelector('[role="tooltip"]')
  expect(card?.textContent).toContain('84.2%')
  expect(card?.textContent).toContain('Likely 82.1–86.2%, from 1,216 clients.')
})
