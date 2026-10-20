import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { KPI_LABELS, useOrgDirectory } from '../../data'
import { destinations, search } from './search'

/**
 * Jump anywhere: a page, any region, district or branch, or a measure. Opens with ⌘K, Ctrl+K
 * or "/" (outside text fields). A native <dialog>, so focus is trapped and Escape closes it.
 * The org directory loads the first time the palette opens.
 */
export function CommandPalette() {
  const navigate = useNavigate()
  const dialog = useRef<HTMLDialogElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const listId = useId()
  const [open, setOpen] = useState(false)
  const [wanted, setWanted] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const directory = useOrgDirectory(wanted)
  const all = useMemo(() => destinations(directory.status === 'ready' ? directory.data : [], KPI_LABELS), [directory])
  const results = useMemo(() => search(all, query), [all, query])

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      const target = event.target as HTMLElement
      const typing = target.closest('input, textarea, select, [contenteditable="true"]')
      if ((event.key === 'k' && (event.metaKey || event.ctrlKey)) || (event.key === '/' && !typing)) {
        event.preventDefault()
        setOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (open && !element.open) {
      setWanted(true)
      setQuery('')
      setActive(0)
      element.showModal()
      input.current?.focus()
    } else if (!open && element.open) element.close()
  }, [open])

  // `close` is dispatched after the dialog closes; if it was reopened meanwhile, the stale
  // event is ignored (onClose checks `open`), so a quick close-then-reopen stays open.
  const go = (href: string) => {
    setOpen(false)
    navigate(href)
  }
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive((i) => Math.min(results.length - 1, i + 1)) }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setActive((i) => Math.max(0, i - 1)) }
    else if (event.key === 'Enter' && results[active]) { event.preventDefault(); go(results[active]!.href) }
    // A search field eats the first Escape to clear itself, so close the palette here instead.
    else if (event.key === 'Escape') { event.preventDefault(); setOpen(false) }
  }

  return <>
    <button type="button" className="palette-open" onClick={() => setOpen(true)} aria-keyshortcuts="Meta+K Control+K /" aria-label="Jump to a page, area or measure">
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" /><path d="m10.5 10.5 3 3" /></svg>
      <span>Jump to</span><kbd>⌘K</kbd>
    </button>
    <dialog ref={dialog} className="palette" aria-label="Jump to a page, area or measure" onClose={() => { if (!dialog.current?.open) setOpen(false) }}
      onClick={(event) => { if (event.target === dialog.current) setOpen(false) }}>
      <div className="palette-box">
        <input ref={input} type="search" value={query} placeholder="Search regions, districts, branches, measures…"
          role="combobox" aria-expanded="true" aria-controls={listId} aria-activedescendant={results[active] ? `${listId}-${active}` : undefined}
          aria-label="Search" onChange={(event) => { setQuery(event.target.value); setActive(0) }} onKeyDown={onKeyDown} />
        <ul id={listId} role="listbox" className="palette-list">
          {results.map((d, i) => <li key={d.id} id={`${listId}-${i}`} role="option" aria-selected={i === active}
            onPointerMove={() => setActive(i)} onClick={() => go(d.href)}>
            <span className="palette-kind">{d.kind}</span>
            <span className="palette-label">{d.label}</span>
            {d.hint && <span className="palette-hint">{d.hint}</span>}
          </li>)}
          {results.length === 0 && <li className="palette-empty" role="presentation">{directory.status === 'loading' ? 'Loading the branch network…' : `Nothing matches “${query}”.`}</li>}
        </ul>
        <p className="palette-keys"><kbd>↑</kbd><kbd>↓</kbd> move <kbd>Enter</kbd> open <kbd>Esc</kbd> close</p>
      </div>
    </dialog>
  </>
}
