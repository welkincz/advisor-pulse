import { useEffect, useId, useRef, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

const navigation = [
  ['/', 'Overview'], ['/map', 'Map'], ['/pipeline', 'Pipeline'],
  ['/quality', 'Data quality'], ['/case-study', 'Case study'],
] as const

/**
 * The main navigation. Wide screens show the links inline; on a phone they fold behind a
 * "Menu" button (a disclosure, so screen readers hear expanded or collapsed) and open as a
 * list under the header. Choosing a page or pressing Escape folds it again.
 */
export function SiteNav() {
  const [open, setOpen] = useState(false)
  const listId = useId()
  const button = useRef<HTMLButtonElement>(null)
  const { pathname } = useLocation()
  const current = navigation.find(([path]) => (path === '/' ? pathname === '/' : pathname.startsWith(path)))?.[1]

  useEffect(() => { setOpen(false) }, [pathname])
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); button.current?.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return <nav className={`site-nav${open ? ' is-open' : ''}`} aria-label="Main navigation">
    <button ref={button} type="button" className="site-nav-toggle" aria-expanded={open} aria-controls={listId} onClick={() => setOpen((o) => !o)}>
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">{open ? <path d="m4 4 8 8M12 4l-8 8" /> : <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" />}</svg>
      <span>Menu</span>{current && <span className="site-nav-current">{current}</span>}
    </button>
    <div id={listId} className="site-nav-links">
      {navigation.map(([path, label]) => <NavLink key={path} to={path} end={path === '/'} viewTransition>{label}</NavLink>)}
    </div>
  </nav>
}
