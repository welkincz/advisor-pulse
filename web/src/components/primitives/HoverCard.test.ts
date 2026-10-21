import { describe, expect, it } from 'vitest'
import { placeCard } from './HoverCard'

const card = { width: 200, height: 100 }

describe('placeCard', () => {
  it('sits above and centred on the trigger when there is room', () => {
    expect(placeCard({ top: 300, bottom: 320, left: 400, width: 100 }, card, 1200)).toEqual({ left: 350, top: 192, below: false })
  })

  it('drops below when the top of the viewport is too close', () => {
    expect(placeCard({ top: 60, bottom: 80, left: 400, width: 100 }, card, 1200)).toEqual({ left: 350, top: 88, below: true })
  })

  it('stays inside a 16 px gutter at either edge of a 375 px screen', () => {
    expect(placeCard({ top: 300, bottom: 320, left: 0, width: 40 }, card, 375).left).toBe(16)
    expect(placeCard({ top: 300, bottom: 320, left: 340, width: 30 }, card, 375).left).toBe(159)
  })
})
