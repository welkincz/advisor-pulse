/** A label's box on the canvas, in CSS pixels: both text lines, halo excluded. */
export interface LabelBox { x: number; y: number; width: number; height: number }

/** Labels keep this many pixels clear of the canvas edge, or hide. */
export const LABEL_PAD = 4

/**
 * Whether a label's whole box sits inside the canvas with `pad` to spare on every side.
 * A label that fails hides rather than show a clipped fragment; the list beside the map has every value.
 */
export function labelFits(box: LabelBox, canvas: { width: number; height: number }, pad = LABEL_PAD): boolean {
  return box.x >= pad && box.y >= pad
    && box.x + box.width <= canvas.width - pad
    && box.y + box.height <= canvas.height - pad
}
