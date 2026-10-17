import { useSyncExternalStore } from 'react'

const query = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  ? window.matchMedia('(prefers-reduced-motion: reduce)') : null
const subscribe = (onChange: () => void) => {
  query?.addEventListener('change', onChange)
  return () => query?.removeEventListener('change', onChange)
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, () => query?.matches ?? false)
}
