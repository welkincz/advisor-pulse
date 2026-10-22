import { useCallback, useSyncExternalStore } from 'react'

/** Whether a media query matches now; re-renders when it changes (a rotated phone, a resized window). */
export function useMedia(query: string): boolean {
  const list = useCallback(() => (typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(query) : null), [query])
  const subscribe = useCallback((onChange: () => void) => {
    const media = list()
    media?.addEventListener('change', onChange)
    return () => media?.removeEventListener('change', onChange)
  }, [list])
  return useSyncExternalStore(subscribe, () => list()?.matches ?? false, () => false)
}

/** The hero chart's height: sized to its question, shorter on a phone so the figure and the board stay close. */
export function heroChartHeight(wide: boolean, phone: boolean): number {
  return wide ? 240 : phone ? 180 : 220
}
