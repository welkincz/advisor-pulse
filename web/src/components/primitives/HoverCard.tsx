import { type FocusEvent, type PointerEvent, type ReactNode, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
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
/** Time to move the pointer from the trigger onto the card before it closes. */
const CLOSE_DELAY = 120

export interface Placement { left: number; top: number; below: boolean }

/** Above the trigger when the card fits there, else below; centred on it, inside a 16 px gutter. */
export function placeCard(anchor: { top: number; bottom: number; left: number; width: number }, card: { width: number; height: number }, viewportWidth: number): Placement {
  const below = anchor.top - card.height - GAP < GUTTER
  const left = Math.max(GUTTER, Math.min(viewportWidth - GUTTER - card.width, anchor.left + anchor.width / 2 - card.width / 2))
  return { left, top: below ? anchor.bottom + GAP : anchor.top - card.height - GAP, below }
}

interface TriggerProps {
  'aria-describedby'?: string
}

/**
 * Shows a hover card for its children: on pointer hover after a short pause (so passing over a
 * page does not flash cards), at once on keyboard focus, and on a tap on touch screens. The
 * pointer can move onto the card without closing it. Esc, leaving, blur or a tap elsewhere
 * closes it, and it follows its trigger when the page scrolls. It is portalled, so no
 * overflow clips it.
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
  const anchor = useRef<HTMLElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const timer = useRef(0)
  const touched = useRef(false)
  const [open, setOpen] = useState(false)
  const [place, setPlace] = useState<Placement | null>(null)

  const close = useCallback(() => { window.clearTimeout(timer.current); setOpen(false); setPlace(null) }, [])
  const closeSoon = useCallback(() => { window.clearTimeout(timer.current); timer.current = window.setTimeout(close, CLOSE_DELAY) }, [close])
  const keep = () => window.clearTimeout(timer.current)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const measure = useCallback(() => {
    if (!anchor.current || !panel.current) return
    const p = panel.current.getBoundingClientRect()
    setPlace(placeCard(anchor.current.getBoundingClientRect(), p, window.innerWidth))
  }, [])
  useLayoutEffect(() => { if (open) measure() }, [open, measure])

  useEffect(() => {
    if (!open) return
    let frame = 0
    // Follow the trigger when the page scrolls (focus scrolls a row into view) or resizes.
    const follow = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(measure) }
    // Esc closes a card opened by hover too, wherever focus is.
    const onKey = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') close() }
    const onTapElsewhere = (event: globalThis.PointerEvent) => {
      const target = event.target as Node
      if (!anchor.current?.contains(target) && !panel.current?.contains(target)) close()
    }
    window.addEventListener('scroll', follow, { passive: true, capture: true })
    window.addEventListener('resize', follow)
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onTapElsewhere)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', follow, { capture: true })
      window.removeEventListener('resize', follow)
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onTapElsewhere)
    }
  }, [open, measure, close])

  const onPointerEnter = (event: PointerEvent) => {
    if (event.pointerType === 'touch') return
    keep()
    timer.current = window.setTimeout(() => setOpen(true), OPEN_DELAY)
  }
  const onPointerLeave = (event: PointerEvent) => { if (event.pointerType !== 'touch') closeSoon() }
  // A tap opens the card on touch screens, where there is no hover; a second tap closes it.
  const onPointerDown = (event: PointerEvent) => { touched.current = event.pointerType === 'touch' }
  const onClick = () => { if (touched.current) setOpen((was) => !was) }
  const onFocus = (event: FocusEvent) => { if (event.target.matches(':focus-visible')) setOpen(true) }
  const onBlur = (event: FocusEvent) => { if (!anchor.current?.contains(event.relatedTarget as Node | null)) close() }

  const content = typeof card === 'function' ? (open ? card() : null) : card
  const Tag = block ? 'div' : 'span'
  return <Tag ref={anchor as never} className={`explain${block ? ' explain-block' : ''}${className ? ` ${className}` : ''}`}
    onPointerEnter={onPointerEnter} onPointerLeave={onPointerLeave} onPointerDown={onPointerDown} onClick={onClick} onFocus={onFocus} onBlur={onBlur}>
    {typeof children === 'function' ? children(open ? { 'aria-describedby': id } : {}) : children}
    {open && content && createPortal(<div ref={panel} className={`hc-layer${place ? ' is-placed' : ''}${place?.below ? ' is-below' : ''}`}
      style={place ? { left: place.left, top: place.top } : { left: 0, top: 0 }} onPointerEnter={keep} onPointerLeave={closeSoon}>
      <HoverCard card={content} id={id} />
    </div>, document.body)}
  </Tag>
}

/** A word the reader may not know, underlined with dots; hover, focus or a tap explains it. */
export function Term({ title, text, children }: { title: string; text: ReactNode; children?: ReactNode }) {
  return <Explain card={{ title, what: text }}>
    {(props) => <span className="term" tabIndex={0} {...props}>{children ?? title}</span>}
  </Explain>
}
