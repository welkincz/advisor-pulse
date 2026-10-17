import { flushSync } from 'react-dom'
import type { NavigateFunction } from 'react-router-dom'

/** The shared name: the clicked child's label morphs into the next page's heading. */
export const TITLE_TRANSITION = 'drill-title'

type StartViewTransition = (update: () => void) => { ready: Promise<void>; finished: Promise<void> }

/** On <html> while the old page is captured: the current heading gives up the name. */
export const FROM_ROW_CLASS = 'drill-from-row'

/**
 * Follow a child link inside a view transition when the browser has them and motion is
 * allowed; otherwise let the link navigate as usual.
 */
export function navigateWithTransition(event: React.MouseEvent<HTMLAnchorElement>, href: string, navigate: NavigateFunction, reducedMotion: boolean) {
  const start = (document as Document & { startViewTransition?: StartViewTransition }).startViewTransition
  if (!start || reducedMotion || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
  event.preventDefault()
  const link = event.currentTarget
  const root = document.documentElement
  link.style.viewTransitionName = TITLE_TRANSITION
  root.classList.add(FROM_ROW_CLASS)
  const transition = start.call(document, () => {
    link.style.viewTransitionName = ''
    root.classList.remove(FROM_ROW_CLASS)
    flushSync(() => navigate(href))
  })
  // A skipped transition (e.g. the tab is hidden) still navigates; nothing to report.
  transition.ready.catch(() => root.classList.remove(FROM_ROW_CLASS))
  transition.finished.catch(() => undefined)
}
