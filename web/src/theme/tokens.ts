import { useSyncExternalStore } from 'react'

/** Read a token from :root, so charts and canvases use the same values as the CSS. */
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim()
}

export type ColorScheme = 'light' | 'dark'

const dark = window.matchMedia('(prefers-color-scheme: dark)')
const subscribe = (onChange: () => void) => {
  dark.addEventListener('change', onChange)
  return () => dark.removeEventListener('change', onChange)
}

/** The active scheme; tokens.css switches on the same media query. */
export function useColorScheme(): ColorScheme {
  return useSyncExternalStore(subscribe, () => (dark.matches ? 'dark' : 'light'))
}

export const SERIES = ['series-1', 'series-2', 'series-3', 'series-4'] as const
export const SEQUENTIAL = ['seq-1', 'seq-2', 'seq-3', 'seq-4', 'seq-5', 'seq-6', 'seq-7'] as const
export const DIVERGING = ['worse-3', 'worse-2', 'worse-1', 'diverging-mid', 'better-1', 'better-2', 'better-3'] as const
