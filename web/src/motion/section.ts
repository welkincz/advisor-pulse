/** Opacity only: entry order is visible without changing layout geometry. */
export function sectionEntrance(order: number, reducedMotion: boolean) {
  return {
    initial: reducedMotion ? false : { opacity: 0 },
    animate: { opacity: 1 },
    transition: { duration: reducedMotion ? 0 : 0.24, delay: reducedMotion ? 0 : Math.min(order, 3) * 0.08, ease: [0.2, 0, 0, 1] as [number, number, number, number] },
  }
}
