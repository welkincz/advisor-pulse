import { type KeyboardEvent, type PointerEvent, type ReactNode, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useReducedMotion } from '../../app/useReducedMotion'
import { weekFiscalYear } from '../../data/fiscal'
import { standardEase } from '../../motion/tween'
import { type Pt, annotatedWeek, domain, linePath, mixPoints, ticks } from './scale'
import './charts.css'

const MORPH_MS = 620

export interface TrendChartProps {
  /** One label per point, oldest first (ISO week ids). */
  weeks: readonly string[]
  /** The measure, one value per week; null breaks the line. */
  values: readonly (number | null)[]
  /** The trailing 13-week average, drawn as a soft ribbon: what a usual week looks like. */
  usual?: readonly (number | null)[]
  /** A comparison line drawn underneath in hairline, e.g. the national figure. */
  reference?: readonly (number | null)[]
  /** Weeks flagged as anomalies get a dot; a full chart also circles one of them (see `annotatedWeek`). */
  flagged?: readonly boolean[]
  selected?: string
  onSelect?: (week: string) => void
  format: (value: number | null | undefined) => string
  label: string
  height?: number
  /** Small-multiple mode: no axes, no tooltip, a lighter line. */
  compact?: boolean
  /** CSS colour for the line; ink by default. */
  color?: string
  /** Extra rows for the tooltip, e.g. a definition or the week's WoW. */
  tip?: (index: number) => ReactNode
  /** What happened that week, in short lines; replaces the default usual and anomaly rows. */
  describe?: (index: number) => readonly string[]
  /** The tooltip's last line: what a click does. */
  hint?: string
  /** Change this to morph the line from the previous measure instead of redrawing. */
  morphKey?: string
  /** Fit the y axis from this index on, so warm-up weeks do not flatten the rest. */
  fitFrom?: number
  /** False when no data is coming (the load failed): the empty chart's placeholder stops pulsing. */
  loading?: boolean
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    setWidth(element.clientWidth)
    const observer = new ResizeObserver(() => setWidth(element.clientWidth))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

/**
 * A weekly line in plain SVG. It draws itself once on first view, morphs when the measure
 * changes, and moves its week cursor when the week does. Hover shows a crosshair and the
 * week's numbers; click or arrow keys choose a week when `onSelect` is given.
 */
export function TrendChart({ weeks, values, usual, reference, flagged, selected, onSelect, format, label, height = 280, compact = false, color, tip, describe, hint, morphKey, fitFrom = 0, loading = true }: TrendChartProps) {
  const reducedMotion = useReducedMotion()
  const clip = useId()
  const [box, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  // Keyboard users move the week with the arrows; the tooltip follows the chosen week for them.
  const [keyed, setKeyed] = useState(false)
  const tipId = useId()
  const tipRef = useRef<HTMLDivElement>(null)
  const [tipSize, setTipSize] = useState({ w: 0, h: 0 })
  const margin = compact ? { top: 6, right: 6, bottom: 6, left: 6 } : { top: 16, right: 12, bottom: 26, left: 48 }
  const innerW = Math.max(0, width - margin.left - margin.right)
  const innerH = Math.max(0, height - margin.top - margin.bottom)

  const scale = useMemo(() => {
    // Fit from `fitFrom` on: warm-up weeks before it may run off the edge (the tooltip still has them).
    const from = fitFrom < weeks.length ? fitFrom : 0
    const y = domain([...values.slice(from), ...(usual ?? []).slice(from), ...(reference ?? []).slice(from)], compact ? 0.12 : 0.1) ?? [0, 1]
    const x = (i: number) => margin.left + (weeks.length > 1 ? (i / (weeks.length - 1)) * innerW : innerW / 2)
    const py = (v: number) => margin.top + innerH - ((v - y[0]) / (y[1] - y[0])) * innerH
    const points = (series?: readonly (number | null)[]): Pt[] => (series ?? []).map((v, i) => (v == null ? null : [x(i), py(v)]))
    return { y, x, py, points }
  }, [values, usual, reference, weeks.length, innerW, innerH, margin.left, margin.top, compact, fitFrom])

  const target = useMemo(() => scale.points(values), [scale, values])
  const usualTarget = useMemo(() => scale.points(usual), [scale, usual])

  // Morph between measures: tween each point from where it was drawn to where it belongs now.
  const [shown, setShown] = useState<{ line: Pt[]; usual: Pt[] }>({ line: target, usual: usualTarget })
  const shownRef = useRef(shown)
  shownRef.current = shown
  const lastKey = useRef(morphKey)
  const lastWidth = useRef(width)
  useEffect(() => {
    const morph = morphKey !== lastKey.current && lastWidth.current === width && !reducedMotion
    lastKey.current = morphKey
    lastWidth.current = width
    if (!morph) { setShown({ line: target, usual: usualTarget }); return }
    const from = shownRef.current
    let frame = 0
    let start: number | null = null
    const step = (now: number) => {
      start ??= now
      const t = standardEase(Math.min(1, (now - start) / MORPH_MS))
      setShown({ line: mixPoints(from.line, target, t), usual: mixPoints(from.usual, usualTarget, t) })
      if (t < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [target, usualTarget, morphKey, width, reducedMotion])

  // Draw the line on once, the first time the chart has a size and data.
  const [drawn, setDrawn] = useState(reducedMotion)
  const hasData = values.some((v) => v != null)
  const drawing = !drawn && hasData && width > 0
  useEffect(() => {
    if (drawn || !width || !hasData) return
    const timer = window.setTimeout(() => setDrawn(true), 1400)
    return () => window.clearTimeout(timer)
  }, [drawn, width, hasData])

  const index = selected ? weeks.indexOf(selected) : -1
  const yTicks = compact ? [] : ticks(scale.y[0], scale.y[1], height < 200 ? 2 : 4)
  // Fiscal years start on 1 November (data/fiscal.ts): a rule where each one begins.
  const fiscal = useMemo(() => weeks.map(weekFiscalYear), [weeks])
  const years = compact ? [] : weeks.flatMap((_, i) => (i > 0 && fiscal[i] !== fiscal[i - 1] ? [{ i, label: fiscal[i]! }] : []))

  const pick = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const fraction = (event.clientX - rect.left - margin.left) / Math.max(1, innerW)
    return Math.max(0, Math.min(weeks.length - 1, Math.round(fraction * (weeks.length - 1))))
  }
  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.key === 'Escape') { setKeyed(false); return }
    if (!onSelect || index < 0) return
    const next = { ArrowLeft: index - 1, ArrowRight: index + 1, Home: 0, End: weeks.length - 1, PageUp: index - 13, PageDown: index + 13 }[event.key]
    if (next === undefined) return
    event.preventDefault()
    setKeyed(true)
    onSelect(weeks[Math.max(0, Math.min(weeks.length - 1, next))]!)
  }

  const linePathD = linePath(shown.line)
  const tipAt = hover ?? (keyed && !compact && index >= 0 ? index : null)
  const tipX = tipAt !== null ? scale.x(tipAt) : 0
  const tipPoint = tipAt !== null ? target[tipAt] : null
  // Clamp by the tooltip's measured width, so a wide one never runs off a narrow screen.
  useLayoutEffect(() => {
    const w = tipRef.current?.offsetWidth ?? 0
    const h = tipRef.current?.offsetHeight ?? 0
    if (w && (w !== tipSize.w || h !== tipSize.h)) setTipSize({ w, h })
  }, [tipAt, tipSize])
  const half = (tipSize.w || 180) / 2
  const tipLeft = Math.min(Math.max(tipX, half + 4), Math.max(half + 4, width - half - 4))
  // Above the point when it fits inside the chart, else below it, so a high week's card stays readable.
  const pointY = tipPoint?.[1] ?? margin.top
  const tipBelow = pointY - 12 - tipSize.h < 0

  // One flagged week circled and named, so the eye finds it before reading the tooltip.
  const ringAt = compact ? null : annotatedWeek(flagged, values, index)
  // On the drawn line, not the raw value: during a morph the ring rides the moving point.
  const ringPoint = ringAt !== null ? shown.line[ringAt] : null
  // An anomaly is an extreme, so its name goes on the outside of the line: below a dip, above a spike.
  const near = ringAt === null ? [] : shown.line.slice(Math.max(0, ringAt - 4), ringAt + 5).filter((p): p is [number, number] => p !== null)
  const latest = annotatedWeek(flagged, values, -1)
  const named = latest !== null && !compact ? `${label} Latest anomaly: ${weeks[latest]}.` : label
  const dip = ringPoint != null && near.length > 0 && ringPoint[1] > near.reduce((sum, p) => sum + p[1], 0) / near.length

  // No values yet: a placeholder in the line's shape, in the plot's place, instead of an empty axis.
  const skeleton = !compact && !hasData

  return <div ref={box} className={`trend${compact ? ' trend-compact' : ''}`} style={{ height }}>
    {skeleton && <div className={`trend-skeleton${loading ? ' is-loading' : ''}`} role="status"
      style={{ inset: `${margin.top}px ${margin.right}px ${margin.bottom}px ${margin.left}px` }}>
      <span className="trend-skeleton-label">{loading ? 'Loading the chart…' : 'No values to plot.'}</span>
      <svg className="trend-skeleton-shape" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
        <path d="M0 27 C8 25 14 30 22 27 S36 17 46 20 S62 28 72 22 S88 13 100 16" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>}
    {width > 0 && !skeleton && <svg width={width} height={height} role="img" aria-label={named}
      tabIndex={onSelect ? 0 : undefined} onKeyDown={onKeyDown} onBlur={() => setKeyed(false)}
      onFocus={(event) => { if (event.currentTarget.matches(':focus-visible')) setKeyed(true) }}
      onPointerMove={compact ? undefined : (event) => { setKeyed(false); setHover(pick(event)) }}
      onPointerLeave={() => setHover(null)}
      onClick={onSelect ? (event) => onSelect(weeks[pick(event as unknown as PointerEvent<SVGSVGElement>)]!) : undefined}
      className={onSelect ? 'trend-svg is-interactive' : 'trend-svg'}>
      <defs><clipPath id={clip}><rect x={margin.left - 6} y={margin.top - 6} width={innerW + 12} height={innerH + 12} /></clipPath></defs>
      {yTicks.map((t) => <g key={`${morphKey}-${t}`} className="trend-tick">
        <line x1={margin.left} x2={margin.left + innerW} y1={scale.py(t)} y2={scale.py(t)} />
        <text x={margin.left - 8} y={scale.py(t)} dy="0.32em" textAnchor="end">{format(t)}</text>
      </g>)}
      {years.map((year) => <g key={year.label} className="trend-year">
        <line x1={scale.x(year.i)} x2={scale.x(year.i)} y1={margin.top} y2={margin.top + innerH} />
        <text x={scale.x(year.i) + 4} y={height - 8}>{year.label}</text>
      </g>)}
      <g clipPath={`url(#${clip})`}>
        {reference && <path className="trend-reference" d={linePath(scale.points(reference))} />}
        {usual && <path className="trend-usual" d={linePath(shown.usual)} />}
        <path className={`trend-line${drawing ? ' is-drawing' : ''}`} d={linePathD} pathLength={drawing ? 1 : undefined}
          style={color ? { stroke: color } : undefined} />
        {flagged?.map((flag, i) => flag && shown.line[i]
          ? <circle key={i} className={`trend-flag${drawing ? ' is-waiting' : ''}`} cx={shown.line[i]![0]} cy={shown.line[i]![1]} r={compact ? 2.5 : 4.5} />
          : null)}
      </g>
      {ringAt !== null && ringPoint && <AnomalyRing key={`${weeks[ringAt]}-${morphKey}`} point={ringPoint} week={weeks[ringAt]!}
        waiting={drawing} dip={dip} covered={tipAt === ringAt} plot={{ left: margin.left, right: margin.left + innerW, top: margin.top, bottom: margin.top + innerH }} />}
      {index >= 0 && <g className="trend-cursor" style={{ transform: `translateX(${scale.x(index)}px)` }}>
        <line x1={0} x2={0} y1={margin.top - 6} y2={margin.top + innerH} />
        {target[index] && <circle cx={0} cy={target[index]![1]} r={compact ? 3 : 5} style={color ? { fill: color } : undefined} />}
      </g>}
      {hover !== null && !compact && <line className="trend-crosshair" x1={tipX} x2={tipX} y1={margin.top} y2={margin.top + innerH} />}
    </svg>}
    {tipAt !== null && !compact && <div ref={tipRef} id={tipId} className={`trend-tip${tipBelow ? ' is-below' : ''}`} aria-live={keyed ? 'polite' : undefined}
      style={{ left: tipLeft, top: tipBelow ? pointY + 12 : pointY - 12 }}>
      <span className="trend-tip-week figure-num">{weeks[tipAt]}</span>
      <strong className="figure-num">{format(values[tipAt])}</strong>
      {describe ? describe(tipAt).map((line) => <span key={line} className="trend-tip-line">{line}</span>) : <>
        {usual && usual[tipAt] != null && <span>Usual {format(usual[tipAt])}</span>}
        {flagged?.[tipAt] && <span className="trend-tip-flag">Anomaly</span>}
      </>}
      {tip?.(tipAt)}
      {hint && onSelect && hover !== null && <span className="trend-tip-hint">{hint}</span>}
    </div>}
  </div>
}

const RING = 11

/**
 * A ring that draws itself round a flagged week, with a short name beside it. It waits for the
 * line to finish drawing, and is keyed by week and measure so it redraws when either changes.
 */
function AnomalyRing({ point, week, waiting, dip, covered, plot }: { point: [number, number]; week: string; waiting: boolean; dip: boolean; covered: boolean; plot: { left: number; right: number; top: number; bottom: number } }) {
  const [x, y] = point
  // Decided once: the line finishing mid-animation must not change the delays under it.
  const [afterLine] = useState(waiting)
  // Outside the line when there is room there, else the other side; toward the plot's middle so it never runs off.
  const roomAbove = y - RING - 18 >= plot.top
  const roomBelow = y + RING + 16 <= plot.bottom + 20
  const above = dip ? !roomBelow : roomAbove
  const toLeft = x > (plot.left + plot.right) / 2
  const short = week.slice(week.indexOf('-') + 1)
  return <g className={`trend-ring${afterLine ? ' is-waiting' : ''}${covered ? ' is-covered' : ''}`} aria-hidden="true">
    <circle className="trend-ring-circle" cx={x} cy={y} r={RING} pathLength={1} transform={`rotate(-90 ${x} ${y})`} />
    <text className="trend-ring-label" x={x + (toLeft ? -RING : RING)} y={above ? y - RING - 6 : y + RING + 14} textAnchor={toLeft ? 'end' : 'start'}>
      Anomaly <tspan className="trend-ring-week">{short}</tspan>
    </text>
  </g>
}
