import { describe, expect, it } from 'vitest'
import { LABEL_PAD, labelFits, labelRank, shortBox, spreadLabels } from './labels'

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

describe('spreadLabels', () => {
  const item = (id: string, x: number, y: number, width = 96, height = 32) =>
    ({ id, full: { x, y, width, height }, name: { x, y, width, height: height / 2 } })
  type Item = ReturnType<typeof item>
  const box = (i: Item, p: { dx: number; dy: number; value: boolean }) =>
    ({ x: i.full.x + p.dx, y: i.full.y + p.dy, width: i.full.width, height: p.value ? i.full.height : i.name.height })
  const apart = (a: ReturnType<typeof box>, b: ReturnType<typeof box>) =>
    a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y

  it('leaves labels that do not touch where they are', () => {
    const spots = spreadLabels([item('ON', 300, 300), item('QC', 500, 200)], desktop)
    expect(spots.map((s) => [s.dx, s.dy, s.value, s.visible])).toEqual([[0, 0, true, true], [0, 0, true, true]])
  })

  it('moves Saskatchewan off Manitoba, as at 1440 px, keeping both names whole', () => {
    const items = [item('MB', 270, 300, 70), item('SK', 186, 302, 96)]
    const spots = spreadLabels(items, desktop)
    expect(spots[0]).toEqual({ id: 'MB', dx: 0, dy: 0, value: true, short: false, visible: true })
    expect(spots[1]).toMatchObject({ visible: true, value: true })
    expect(apart(box(items[0]!, spots[0]!), box(items[1]!, spots[1]!))).toBe(true)
  })

  it('slides a label that overhangs the edge back inside instead of hiding it', () => {
    const [spot] = spreadLabels([item('BC', -40, 90, 110)], phone)
    expect(spot!.visible).toBe(true)
    expect(spot!.dx).toBeGreaterThanOrEqual(44)
  })

  it('hides a label mostly off the canvas: its province is out of view', () => {
    expect(spreadLabels([item('NL', 330, 90, 110)], phone)[0]!.visible).toBe(false)
  })

  it('pulls a leader-line label fully inside while its province is in view (Nova Scotia at 375 px)', () => {
    const ns = { ...item('NS', 330, 120, 20, 32), at: [300, 110] as const }
    const [spot] = spreadLabels([ns], phone)
    expect(spot!.visible).toBe(true)
    expect(330 + spot!.dx + 20).toBeLessThanOrEqual(phone.width - LABEL_PAD)
    expect(spreadLabels([{ ...ns, at: [400, 110] as const }], phone)[0]!.visible).toBe(false)
  })

  it('drops every value line, not just one, when a label would otherwise hide (a phone)', () => {
    const spots = spreadLabels([item('ON', 10, 6), item('QC', 10, 26)], { width: 220, height: 60 })
    expect(spots.map((s) => [s.visible, s.value])).toEqual([[true, false], [true, false]])
  })

  it('shows the short code when even the name has no room, and hides only when the code has none', () => {
    const strip = { width: 220, height: 28 }
    const sk = item('SK', 100, 6)
    const spots = spreadLabels([item('ON', 10, 6), { ...sk, short: shortBox(sk.name, 'Saskatchewan', 'SK') }, item('MB', 60, 6)], strip)
    expect(spots[0]).toMatchObject({ visible: true, value: false, short: false })
    expect(spots[1]).toMatchObject({ visible: true, short: true })
    expect(spots[2]).toMatchObject({ visible: false })
  })

  it('estimates a short code box at the name\'s anchor', () => {
    const name = { x: 100, y: 10, width: 120, height: 16 }
    expect(shortBox(name, 'Saskatchewan', 'SK')).toEqual({ x: 145, y: 10, width: 30, height: 16 })
    expect(shortBox(name, 'Saskatchewan', 'SK', 'start').x).toBe(100)
    expect(shortBox(name, 'Saskatchewan', 'SK', 'end').x).toBe(190)
  })

  it('ranks the large provinces first and unknown regions last', () => {
    expect(['PE', 'ON', 'XX', 'SK'].sort((a, b) => labelRank(a) - labelRank(b))).toEqual(['ON', 'SK', 'PE', 'XX'])
  })
})
