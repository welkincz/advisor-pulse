import { type KeyboardEvent, type PointerEvent, type ReactNode, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useReducedMotion } from '../../app/useReducedMotion'
import { standardEase } from '../../motion/tween'
import { type Pt, domain, linePath, mixPoints, ticks } from './scale'
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
  /** Weeks flagged as anomalies get a ring. */
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
  /** Change this to morph the line from the previous measure instead of redrawing. */
  morphKey?: string
  /** Fit the y axis from this index on, so warm-up weeks do not flatten the rest. */
  fitFrom?: number
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
export function TrendChart({ weeks, values, usual, reference, flagged, selected, onSelect, format, label, height = 280, compact = false, color, tip, morphKey, fitFrom = 0 }: TrendChartProps) {
  const reducedMotion = useReducedMotion()
  const clip = useId()
  const [box, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
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
  const years = compact ? [] : weeks.flatMap((w, i) => (i > 0 && w.slice(0, 4) !== weeks[i - 1]!.slice(0, 4) ? [{ i, label: w.slice(0, 4) }] : []))
  const active = hover ?? (index >= 0 ? index : null)

  const pick = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const fraction = (event.clientX - rect.left - margin.left) / Math.max(1, innerW)
    return Math.max(0, Math.min(weeks.length - 1, Math.round(fraction * (weeks.length - 1))))
  }
  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    if (!onSelect || index < 0) return
    const next = { ArrowLeft: index - 1, ArrowRight: index + 1, Home: 0, End: weeks.length - 1, PageUp: index - 13, PageDown: index + 13 }[event.key]
    if (next === undefined) return
    event.preventDefault()
    onSelect(weeks[Math.max(0, Math.min(weeks.length - 1, next))]!)
  }

  const linePathD = linePath(shown.line)
  const tipX = active !== null ? scale.x(active) : 0
  const tipPoint = active !== null ? target[active] : null

  return <div ref={box} className={`trend${compact ? ' trend-compact' : ''}`} style={{ height }}>
    {width > 0 && <svg width={width} height={height} role="img" aria-label={label}
      tabIndex={onSelect ? 0 : undefined} onKeyDown={onKeyDown}
      onPointerMove={compact ? undefined : (event) => setHover(pick(event))}
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
      {index >= 0 && <g className="trend-cursor" style={{ transform: `translateX(${scale.x(index)}px)` }}>
        <line x1={0} x2={0} y1={margin.top - 6} y2={margin.top + innerH} />
        {target[index] && <circle cx={0} cy={target[index]![1]} r={compact ? 3 : 5} style={color ? { fill: color } : undefined} />}
      </g>}
      {hover !== null && !compact && <line className="trend-crosshair" x1={tipX} x2={tipX} y1={margin.top} y2={margin.top + innerH} />}
    </svg>}
    {hover !== null && !compact && <div className="trend-tip" style={{ left: Math.min(Math.max(tipX, 90), width - 90), top: Math.max(0, (tipPoint?.[1] ?? margin.top) - 12) }}>
      <span className="trend-tip-week figure-num">{weeks[hover]}</span>
      <strong className="figure-num">{format(values[hover])}</strong>
      {usual && usual[hover] != null && <span>Usual {format(usual[hover])}</span>}
      {flagged?.[hover] && <span className="trend-tip-flag">Anomaly</span>}
      {tip?.(hover)}
    </div>}
  </div>
}
