import { type KeyboardEvent, useId, useLayoutEffect, useRef, useState } from 'react'
import { fitted, ticks } from '../../components/charts/scale'
import { quarterLabel, quarterMonths } from '../../data/fiscal'
import { type QuarterPoint, toDate } from './quarters'
import './quarters.css'

function useWidth() {
  const ref = useRef<HTMLDivElement>(null)
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

/** A column with 4 px rounded corners at its data end, anchored square on the baseline. */
function column(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w / 2, h)
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
}

/**
 * The fiscal quarters of one measure, grouped under their fiscal year. A rate (`dots`) is a
 * dot per quarter joined by a line, on an axis fitted to its values so a slide of a point or
 * two shows; the chart says when that axis does not start at zero. A count (`bars`) keeps
 * columns on a zero baseline. A quarter still running is drawn open (an open dot on a dashed
 * line, or a hatched column) and says how many of its weeks are in. Choose a quarter by
 * click or arrow keys; hover shows its months and value.
 */
export function QuarterChart({ points, selected, onSelect, format, tickFormat = format, label, form = 'bars', ceiling, height = 240 }: {
  points: readonly QuarterPoint[]
  selected: string
  onSelect: (id: string) => void
  format: (value: number | null | undefined) => string
  /** Axis ticks, when they need fewer decimals than the values (5,000 rather than 5,000.0). */
  tickFormat?: (value: number) => string
  label: string
  form?: 'bars' | 'dots'
  /** The highest value the measure can take (1 for a share), so a fitted axis stops there. */
  ceiling?: number
  height?: number
}) {
  const hatch = useId()
  const [box, width] = useWidth()
  const [hover, setHover] = useState<number | null>(null)
  const dots = form === 'dots'
  const margin = { top: dots ? 34 : 22, right: dots ? 12 : 4, bottom: 44, left: 52 }
  const innerW = Math.max(0, width - margin.left - margin.right)
  const innerH = height - margin.top - margin.bottom
  const top = Math.max(0, ...points.map((p) => p.value ?? 0))
  const fit = dots ? fitted(points.map((p) => p.value), 4, 0.15, ceiling) : null
  const yTicks = fit?.ticks ?? ticks(0, top || 1, 3)
  const yMin = fit?.lo ?? 0
  const yMax = fit?.hi ?? (Math.max(top, yTicks.at(-1) ?? top) || 1)
  const band = innerW / Math.max(1, points.length)
  const barW = Math.min(56, Math.max(4, band * 0.62))
  const base = margin.top + innerH
  const y = (v: number) => base - ((v - yMin) / (yMax - yMin || 1)) * innerH
  const cx = (i: number) => margin.left + band * (i + 0.5)
  // Direct labels on every quarter while they fit; otherwise only on the chosen one.
  const roomy = band >= 46
  const years = points.reduce<{ label: string; from: number; to: number }[]>((groups, p, i) => {
    const year = p.id.slice(0, 4)
    if (groups.at(-1)?.label === year) groups.at(-1)!.to = i
    else groups.push({ label: year, from: i, to: i })
    return groups
  }, [])
  const index = points.findIndex((p) => p.id === selected)
  const active = hover ?? (index >= 0 ? index : null)
  // Line segments between neighbouring quarters; dashed where either end is still running.
  const segments = dots ? points.slice(1).flatMap((p, k) => {
    const prev = points[k]!
    return prev.value == null || p.value == null ? [] : [{ key: p.id, x1: cx(k), y1: y(prev.value), x2: cx(k + 1), y2: y(p.value), open: !prev.complete || !p.complete }]
  }) : []

  const at = (clientX: number, svg: SVGSVGElement) => {
    const i = Math.floor((clientX - svg.getBoundingClientRect().left - margin.left) / band)
    return i >= 0 && i < points.length ? i : null
  }
  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const next = { ArrowLeft: index - 1, ArrowRight: index + 1, Home: 0, End: points.length - 1 }[event.key]
    if (next === undefined || !points.length) return
    event.preventDefault()
    onSelect(points[Math.max(0, Math.min(points.length - 1, next))]!.id)
  }

  return <div ref={box} className={`quarters-chart${dots ? ' is-dots' : ''}`} style={{ height }}>
    {width > 0 && <svg width={width} height={height} role="img" aria-label={label} tabIndex={0} onKeyDown={onKeyDown}
      onPointerLeave={() => setHover(null)}
      onPointerMove={(event) => setHover(at(event.clientX, event.currentTarget))}
      onClick={(event) => {
        // From the click itself, so a tap on a touch screen (no hover first) chooses too.
        const i = at(event.clientX, event.currentTarget)
        if (i !== null) onSelect(points[i]!.id)
      }}>
      <defs>
        <pattern id={hatch} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="5" className="quarters-hatch" />
        </pattern>
      </defs>
      {yTicks.map((t) => <g key={t} className="trend-tick">
        <line x1={margin.left} x2={margin.left + innerW} y1={y(t)} y2={y(t)} />
        <text x={margin.left - 8} y={y(t)} dy="0.32em" textAnchor="end">{tickFormat(t)}</text>
      </g>)}
      {yMin > 0 && <text className="quarters-axis-note" x={0} y={12}>Axis starts at {tickFormat(yMin)}, not 0</text>}
      {years.map((year, g) => <g key={year.label} className="quarters-year">
        {g > 0 && <line x1={margin.left + band * year.from} x2={margin.left + band * year.from} y1={margin.top - 8} y2={height - 4} />}
        <text x={(cx(year.from) + cx(year.to)) / 2} y={height - 6} textAnchor="middle">{year.label}</text>
      </g>)}
      {dots && hover !== null && <line className="quarters-guide" x1={cx(hover)} x2={cx(hover)} y1={margin.top} y2={base} />}
      {segments.map((s) => <line key={s.key} className={`quarters-line${s.open ? ' is-open' : ''}`} x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} />)}
      {points.map((p, i) => {
        const chosen = i === index
        const h = p.value == null ? 0 : Math.max(1, base - y(p.value))
        const markTop = dots ? (p.value == null ? base : y(p.value) - 8) : base - h
        return <g key={p.id} className={`quarters-col${chosen ? ' is-chosen' : ''}${p.complete ? '' : ' is-to-date'}${hover === i ? ' is-hot' : ''}`}
          style={{ animationDelay: `${i * 40}ms` }}>
          {dots
            ? p.value != null && <circle cx={cx(i)} cy={y(p.value)} r={chosen ? 6 : 4.5} />
            : h > 0 && <path d={column(cx(i) - barW / 2, base - h, barW, h)} style={p.complete ? undefined : { fill: `url(#${hatch})` }} />}
          <text className="quarters-q" x={cx(i)} y={base + 16} textAnchor="middle">{p.id.slice(5)}</text>
          {(roomy || chosen) && p.value != null && <text className="quarters-label" x={cx(i)} y={markTop - 6} textAnchor="middle">{format(p.value)}</text>}
        </g>
      })}
      {!dots && <line className="quarters-base" x1={margin.left} x2={margin.left + innerW} y1={base} y2={base} />}
    </svg>}
    {hover !== null && active !== null && <div className="trend-tip" style={{ left: Math.min(Math.max(cx(active), 90), width - 90), top: Math.max(0, y(points[active]!.value ?? yMin) - 12) }}>
      <span className="trend-tip-week figure-num">{quarterLabel(points[active]!.id)}, {quarterMonths(points[active]!.start, points[active]!.end)}</span>
      <strong className="figure-num">{format(points[active]!.value)}</strong>
      {toDate(points[active]!) && <span className="trend-tip-line">Still running: {toDate(points[active]!)} so far, shown {dots ? 'as an open dot' : 'hatched'}.</span>}
      {active !== index && <span className="trend-tip-hint">Click to choose this quarter</span>}
    </div>}
  </div>
}
