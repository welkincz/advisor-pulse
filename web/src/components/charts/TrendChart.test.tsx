// @vitest-environment jsdom
import { act } from 'react'
import { type Root, createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { TrendChart, type TrendChartProps } from './TrendChart'

declare global { var IS_REACT_ACT_ENVIRONMENT: boolean }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

// jsdom has no layout: give every box a width so the chart draws.
globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 600 })

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  container = document.createElement('div')
  root = createRoot(container)
})
afterEach(() => act(() => root.unmount()))

const weeks = ['2026-W38', '2026-W39', '2026-W40']
const base: TrendChartProps = { weeks, values: [null, null, null], format: (v) => String(v ?? '–'), label: 'Test measure', selected: '2026-W40', height: 280 }
const render = (props: Partial<TrendChartProps> = {}) => act(() => root.render(<TrendChart {...base} {...props} />))

it('draws a placeholder, not an empty axis, while the values are on their way', async () => {
  await render({ loading: true })
  const skeleton = container.querySelector('.trend-skeleton')
  expect(skeleton).not.toBeNull()
  expect(skeleton!.classList.contains('is-loading')).toBe(true)
  expect(skeleton!.getAttribute('role')).toBe('status')
  expect(container.querySelector('.trend-tick')).toBeNull()
  expect(container.querySelector('.trend-cursor')).toBeNull()
  // Same box as the drawn chart, so nothing below it moves when the data arrives.
  expect((container.querySelector('.trend') as HTMLElement).style.height).toBe('280px')
})

it('swaps the placeholder for the chart in the same box once values arrive', async () => {
  await render({ loading: true })
  await render({ values: [10, 12, 11] })
  expect(container.querySelector('.trend-skeleton')).toBeNull()
  expect(container.querySelector('.trend-line')).not.toBeNull()
  expect(container.querySelectorAll('.trend-tick').length).toBeGreaterThan(0)
  expect((container.querySelector('.trend') as HTMLElement).style.height).toBe('280px')
})

it('settles into a still placeholder when the load finished with nothing to plot', async () => {
  await render({ loading: true })
  await render({ loading: false })
  const skeleton = container.querySelector('.trend-skeleton')!
  expect(skeleton.classList.contains('is-loading')).toBe(false)
  expect(skeleton.textContent).toContain('No values to plot.')
  expect(skeleton.textContent).not.toContain('Loading')
})

it('never claims to be loading unless told so', async () => {
  await render()
  expect(container.querySelector('.trend-skeleton')!.classList.contains('is-loading')).toBe(false)
})

it('keeps small multiples free of placeholders', async () => {
  await render({ compact: true })
  expect(container.querySelector('.trend-skeleton')).toBeNull()
})
