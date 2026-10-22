import { describe, expect, it } from 'vitest'
import { LABEL_PAD, labelFits } from './labels'

const desktop = { width: 760, height: 544 }
const phone = { width: 358, height: 240 }

describe('labelFits', () => {
  it('keeps a central label, such as Ontario on a desktop canvas', () => {
    expect(labelFits({ x: 330, y: 300, width: 60, height: 32 }, desktop)).toBe(true)
  })

  it('hides a label cut by the left edge of a narrow canvas, such as British Columbia at 390 px', () => {
    // The anchor is on screen but half the name would hang past the edge.
    expect(labelFits({ x: -40, y: 90, width: 110, height: 32 }, phone)).toBe(false)
  })

  it('uses the whole box: a label whose baseline fits but whose value line runs off the bottom hides', () => {
    expect(labelFits({ x: 100, y: phone.height - 20, width: 60, height: 32 }, phone)).toBe(false)
  })

  it('uses the whole box at the top too: a name line above the canvas hides', () => {
    expect(labelFits({ x: 100, y: -6, width: 60, height: 32 }, phone)).toBe(false)
  })

  it('keeps the pad on every side, inclusive', () => {
    const w = 50
    const h = 30
    expect(labelFits({ x: LABEL_PAD, y: LABEL_PAD, width: w, height: h }, { width: w + 2 * LABEL_PAD, height: h + 2 * LABEL_PAD })).toBe(true)
    expect(labelFits({ x: LABEL_PAD - 1, y: LABEL_PAD, width: w, height: h }, { width: w + 2 * LABEL_PAD, height: h + 2 * LABEL_PAD })).toBe(false)
    expect(labelFits({ x: LABEL_PAD, y: LABEL_PAD, width: w + 1, height: h }, { width: w + 2 * LABEL_PAD, height: h + 2 * LABEL_PAD })).toBe(false)
  })
})
