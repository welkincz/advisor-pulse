import { type FocusEvent, type KeyboardEvent, type PointerEvent, type ReactNode, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export interface CardContent {
  title: ReactNode
  /** The figure the card is about, set large beside the title. */
  value?: ReactNode
  /** What it is: one plain sentence. */
  what?: ReactNode
  /** What happened: short lines written from the data. */
  happened?: readonly ReactNode[]
  /** The question the visual is likely to raise, answered on the spot. */
  answer?: { q: string; a: ReactNode }
  /** What a click or Enter does next. */
  hint?: string
}

/** The card itself. Charts that track the pointer place it themselves; `Explain` places it for anything else. */
export function HoverCard({ card, id }: { card: CardContent; id?: string }) {
  return <div className="hc" role="tooltip" id={id}>
    <p className="hc-head"><span className="hc-title">{card.title}</span>{card.value != null && <span className="hc-value figure-num">{card.value}</span>}</p>
    {card.what && <p className="hc-what">{card.what}</p>}
    {card.happened && card.happened.length > 0 && <ul className="hc-happened" aria-label="What happened">
      {card.happened.map((line, i) => <li key={i}>{line}</li>)}
    </ul>}
    {card.answer && <div className="hc-answer"><p className="hc-q">{card.answer.q}</p><p className="hc-a">{card.answer.a}</p></div>}
    {card.hint && <p className="hc-hint">{card.hint}</p>}
  </div>
}

const GUTTER = 16
const GAP = 8
const OPEN_DELAY = 150

interface TriggerProps {
  'aria-describedby'?: string
}

/**
 * Shows a hover card for its children on pointer hover (after a short pause, so passing over
 * a page does not flash cards) and at once on keyboard focus. Esc, leaving, blur or scrolling
 * closes it. The card sits above the trigger when there is room, else below, inside a 16px
 * gutter, and is portalled so no overflow clips it.
 *
 * Pass a function as children to put `aria-describedby` on the focusable element inside.
 */
export function Explain({ card, children, block = false, className }: {
  card: CardContent | (() => CardContent)
  children: ReactNode | ((props: TriggerProps) => ReactNode)
  block?: boolean
  className?: string
}) {
  const id = useId()
  const anchor = useRef<HTMLSpanElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const timer = useRef(0)
  const [open, setOpen] = useState(false)
  const [place, setPlace] = useState<{ left: number; top: number; below: boolean } | null>(null)

  const close = useCallback(() => { window.clearTimeout(timer.current); setOpen(false); setPlace(null) }, [])
  useEffect(() => () => window.clearTimeout(timer.current), [])
  useEffect(() => {
    if (!open) return
    window.addEventListener('scroll', close, { passive: true, capture: true })
    window.addEventListener('resize', close)
    return () => { window.removeEventListener('scroll', close, { capture: true }); window.removeEventListener('resize', close) }
  }, [open, close])

  useLayoutEffect(() => {
    if (!open || !anchor.current || !panel.current) return
    const a = anchor.current.getBoundingClientRect()
    const p = panel.current.getBoundingClientRect()
    const below = a.top - p.height - GAP < GUTTER
    const left = Math.max(GUTTER, Math.min(window.innerWidth - GUTTER - p.width, a.left + a.width / 2 - p.width / 2))
    setPlace({ left, top: below ? a.bottom + GAP : a.top - p.height - GAP, below })
  }, [open])

  const onPointerEnter = (event: PointerEvent) => {
    if (event.pointerType === 'touch') return
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOpen(true), OPEN_DELAY)
  }
  const onFocus = (event: FocusEvent) => { if (event.target.matches(':focus-visible')) setOpen(true) }
  const onBlur = (event: FocusEvent) => { if (!anchor.current?.contains(event.relatedTarget as Node | null)) close() }
  const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape' && open) { event.stopPropagation(); close() } }

  const content = typeof card === 'function' ? (open ? card() : null) : card
  const Tag = block ? 'div' : 'span'
  return <Tag ref={anchor as never} className={`explain${block ? ' explain-block' : ''}${className ? ` ${className}` : ''}`}
    onPointerEnter={onPointerEnter} onPointerLeave={close} onFocus={onFocus} onBlur={onBlur} onKeyDown={onKeyDown}>
    {typeof children === 'function' ? children(open ? { 'aria-describedby': id } : {}) : children}
    {open && content && createPortal(<div ref={panel} className={`hc-layer${place ? ' is-placed' : ''}${place?.below ? ' is-below' : ''}`}
      style={place ? { left: place.left, top: place.top } : { left: 0, top: 0 }}>
      <HoverCard card={content} id={id} />
    </div>, document.body)}
  </Tag>
}

/** A word the reader may not know, underlined with dots; hover or focus explains it. */
export function Term({ title, text, children }: { title: string; text: ReactNode; children?: ReactNode }) {
  return <Explain card={{ title, what: text }}>
    {(props) => <span className="term" tabIndex={0} {...props}>{children ?? title}</span>}
  </Explain>
}
