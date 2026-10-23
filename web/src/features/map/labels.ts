/** A label's box on the canvas, in CSS pixels: both text lines, halo excluded. */
export interface LabelBox { x: number; y: number; width: number; height: number }

/** Labels keep this many pixels clear of the canvas edge, or hide. */
export const LABEL_PAD = 4

/** Clear space kept between two labels, so their paper halos do not touch. */
export const LABEL_GAP = 4

/**
 * Whether a label's whole box sits inside the canvas with `pad` to spare on every side.
 * A label that fails hides rather than show a clipped fragment; the list beside the map has every value.
 */
export function labelFits(box: LabelBox, canvas: { width: number; height: number }, pad = LABEL_PAD): boolean {
  return box.x >= pad && box.y >= pad
    && box.x + box.width <= canvas.width - pad
    && box.y + box.height <= canvas.height - pad
}

/**
 * The order labels claim space in: the large provinces keep their spot, the crowded prairie
 * middle and the small Atlantic provinces move around them. Unknown regions go last.
 */
const RANK = ['ON', 'QC', 'BC', 'AB', 'MB', 'SK', 'NL', 'NB', 'NS', 'PE']
export function labelRank(region: string): number {
  const at = RANK.indexOf(region)
  return at < 0 ? RANK.length : at
}

/** A box moved by `dx`, `dy` (for an SVG bbox read before its element's translation). */
export function shift(box: LabelBox, dx: number, dy: number): LabelBox {
  return { x: box.x + dx, y: box.y + dy, width: box.width, height: box.height }
}

/**
 * A label to place: its box with both lines (`full`), with the name alone (`name`), and with
 * the province's short code in place of its name (`short`, optional). `at` is the point on the
 * province a label with a leader line belongs to: while it is in view, the label is pulled
 * fully inside the canvas however far it overhangs.
 */
export interface LabelItem { id: string; full: LabelBox; name: LabelBox; short?: LabelBox; at?: readonly [number, number] }

/**
 * Where a label ends up: moved by `dx`, `dy`; `value` false drops the value line; `short`
 * shows the code in place of the name; `visible` false hides it.
 */
export interface LabelPlacement { id: string; dx: number; dy: number; value: boolean; short: boolean; visible: boolean }

function overlaps(a: LabelBox, b: LabelBox, gap: number): boolean {
  return a.x < b.x + b.width + gap && b.x < a.x + a.width + gap
    && a.y < b.y + b.height + gap && b.y < a.y + a.height + gap
}

/** Moves to try for a box, nearest first: small vertical steps, then sideways ones. */
function moves(box: LabelBox): [number, number][] {
  const out: [number, number][] = []
  const sy = Math.max(box.height / 2, 8)
  const sx = Math.max(box.width / 4, 8)
  for (let ring = 0; ring <= 3; ring++) {
    for (const ky of ring === 0 ? [0] : [ring, -ring]) for (const kx of [0, 1, -1, 2, -2]) {
      if (Math.abs(kx) > ring + 1) continue
      out.push([kx * sx, ky * sy])
    }
  }
  return out.sort((a, b) => Math.hypot(a[0] / sx, a[1] / sy) - Math.hypot(b[0] / sx, b[1] / sy))
}

/**
 * Place labels so no two touch and none crosses the canvas edge. Labels are placed in the
 * order given (the first keeps its spot); each later one tries nearby spots, nearest first.
 * A label that only partly overhangs an edge slides back inside; one that cannot find room
 * drops its value line. If any label would still hide, every label drops its value; then a
 * name with no room shows its short code; then every label shows its code. A label hides only
 * when even that has no room (or its province is out of view). A name is never cut.
 */
export function spreadLabels(items: readonly LabelItem[], canvas: { width: number; height: number }, pad = LABEL_PAD, gap = LABEL_GAP): LabelPlacement[] {
  const placed: LabelBox[] = []
  const slide = (box: LabelBox, free = false): [number, number] | null => {
    let dx = 0
    let dy = 0
    if (box.x < pad) dx = pad - box.x
    else if (box.x + box.width > canvas.width - pad) dx = canvas.width - pad - box.x - box.width
    if (box.y < pad) dy = pad - box.y
    else if (box.y + box.height > canvas.height - pad) dy = canvas.height - pad - box.y - box.height
    // A label mostly off the canvas belongs to a province out of view: hide it, do not pin it to the edge.
    if (!free && (Math.abs(dx) > box.width / 2 || Math.abs(dy) > box.height / 2)) return null
    return [dx, dy]
  }
  const find = (box: LabelBox, free: boolean): [number, number] | null => {
    const home = slide(box, free)
    if (!home) return null
    for (const [mx, my] of moves(box)) {
      const moved = { ...box, x: box.x + home[0] + mx, y: box.y + home[1] + my }
      if (!labelFits(moved, canvas, pad)) continue
      if (placed.some((other) => overlaps(moved, other, gap))) continue
      placed.push(moved)
      return [home[0] + mx, home[1] + my]
    }
    return null
  }
  type Form = 'full' | 'name' | 'short'
  const hidden = (id: string): LabelPlacement => ({ id, dx: 0, dy: 0, value: false, short: false, visible: false })
  // Out of view (panned away): hidden whatever the form, and no reason to simplify the others.
  const inView = ([x, y]: readonly [number, number]) => x >= 0 && y >= 0 && x <= canvas.width && y <= canvas.height
  const away = new Set(items.filter((item) => (item.at ? !inView(item.at) : !slide(item.short ?? item.name))).map((item) => item.id))
  const place = (forms: readonly Form[]): LabelPlacement[] => {
    placed.length = 0
    return items.map((item) => {
      if (away.has(item.id)) return hidden(item.id)
      for (const form of forms) {
        const box = item[form]
        const at = box && find(box, item.at !== undefined)
        if (at) return { id: item.id, dx: at[0], dy: at[1], value: form === 'full', short: form === 'short', visible: true }
      }
      return hidden(item.id)
    })
  }
  // A crowded canvas (a phone) gives every label the same, simpler form rather than leave some
  // with values and others without: names alone, then the short code for any name with no room,
  // then codes throughout. If every form still hides one, keep the try that hides fewest.
  const tries: Form[][] = [['full', 'name'], ['name'], ['name', 'short'], ['short', 'name']]
  const missing = (spots: LabelPlacement[]) => spots.filter((s) => !s.visible && !away.has(s.id)).length
  let best: LabelPlacement[] | null = null
  for (const forms of tries) {
    const spots = place(forms)
    if (!best || missing(spots) < missing(best)) best = spots
    if (missing(best) === 0) break
  }
  return best!
}

/**
 * The box a short code (`SK` for Saskatchewan) takes in place of a name, estimated from the
 * name's box: the same height and anchor, and a capital's width per letter.
 */
export function shortBox(name: LabelBox, nameText: string, code: string, anchor: 'start' | 'middle' | 'end' = 'middle'): LabelBox {
  const width = Math.min(name.width, (name.width / Math.max(1, nameText.length)) * code.length * 1.5)
  const x = anchor === 'start' ? name.x : anchor === 'end' ? name.x + name.width - width : name.x + (name.width - width) / 2
  return { x, y: name.y, width, height: name.height }
}
