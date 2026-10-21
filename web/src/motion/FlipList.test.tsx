// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

let reduced = false
vi.mock('../app/useReducedMotion', () => ({ useReducedMotion: () => reduced }))
const { FlipList } = await import('./FlipList')

// jsdom lays nothing out: give each row a top from its place in the list.
Object.defineProperty(HTMLElement.prototype, 'offsetTop', {
  configurable: true,
  get(this: HTMLElement) { return this.dataset.row ? [...this.parentElement!.children].indexOf(this) * 40 : 0 },
})
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function mount(order: string[], animate?: () => void) {
  if (animate) HTMLElement.prototype.animate = animate as never
  else delete (HTMLElement.prototype as { animate?: unknown }).animate
  const host = document.createElement('div')
  const root = createRoot(host)
  const draw = (ids: string[]) => act(() => root.render(<FlipList order={ids}>{ids.map((id) => <li key={id} data-row={id}>{id}</li>)}</FlipList>))
  draw(order)
  return { draw, root }
}

afterEach(() => { reduced = false })

describe('FlipList', () => {
  it('slides each moved row from where it was', () => {
    const animate = vi.fn()
    const { draw, root } = mount(['a', 'b', 'c'], animate)
    draw(['c', 'a', 'b'])
    // c moved up two rows (from 80 to 0); a and b moved down one.
    expect(animate).toHaveBeenCalledTimes(3)
    expect(animate.mock.calls.map((call) => call[0][0].transform)).toContain('translateY(80px)')
    act(() => root.unmount())
  })

  it('jumps under reduced motion, and copes without the Web Animations API', () => {
    reduced = true
    const animate = vi.fn()
    const first = mount(['a', 'b'], animate)
    first.draw(['b', 'a'])
    expect(animate).not.toHaveBeenCalled()
    act(() => first.root.unmount())
    reduced = false
    const second = mount(['a', 'b'])
    expect(() => second.draw(['b', 'a'])).not.toThrow()
    act(() => second.root.unmount())
  })
})
