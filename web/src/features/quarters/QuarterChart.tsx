import { type KeyboardEvent, useId, useLayoutEffect, useRef, useState } from 'react'
import { ticks } from '../../components/charts/scale'
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
 * One column per fiscal quarter on a zero baseline, grouped under its fiscal year. A quarter
 * still running is hatched and says how many of its weeks are in. Choose a quarter by click
 * or arrow keys; hover shows its months and value.
 */
export function QuarterChart({ points, selected, onSelect, format, tickFormat = format, label, height = 240 }: {
  points: readonly QuarterPoint[]
  selected: string
  onSelect: (id: string) => void
  format: (value: number | null | undefined) => string
  /** Axis ticks, when they need fewer decimals than the values (5,000 rather than 5,000.0). */
  tickFormat?: (value: number) => string
  label: string
  height?: number
}) {
  const hatch = useId()
  const [box, width] = useWidth()
  const [hover, setHover] = useState<number | null>(null)
  const margin = { top: 22, right: 4, bottom: 44, left: 52 }
  const innerW = Math.max(0, width - margin.left - margin.right)
  const innerH = height - margin.top - margin.bottom
  const top = Math.max(0, ...points.map((p) => p.value ?? 0))
  const yTicks = ticks(0, top || 1, 3)
  const yMax = Math.max(top, yTicks.at(-1) ?? top) || 1
  const band = innerW / Math.max(1, points.length)
  const barW = Math.min(56, Math.max(4, band * 0.62))
  const y = (v: number) => margin.top + innerH - (v / yMax) * innerH
  const cx = (i: number) => margin.left + band * (i + 0.5)
  // Direct labels on every column while they fit; otherwise only on the chosen one.
  const roomy = band >= 46
  const years = points.reduce<{ label: string; from: number; to: number }[]>((groups, p, i) => {
    const year = p.id.slice(0, 4)
    if (groups.at(-1)?.label === year) groups.at(-1)!.to = i
    else groups.push({ label: year, from: i, to: i })
    return groups
  }, [])
  const index = points.findIndex((p) => p.id === selected)
  const active = hover ?? (index >= 0 ? index : null)

  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const next = { ArrowLeft: index - 1, ArrowRight: index + 1, Home: 0, End: points.length - 1 }[event.key]
    if (next === undefined || !points.length) return
    event.preventDefault()
    onSelect(points[Math.max(0, Math.min(points.length - 1, next))]!.id)
  }

  return <div ref={box} className="quarters-chart" style={{ height }}>
    {width > 0 && <svg width={width} height={height} role="img" aria-label={label} tabIndex={0} onKeyDown={onKeyDown}
      onPointerLeave={() => setHover(null)}
      onPointerMove={(event) => {
        const i = Math.floor((event.clientX - event.currentTarget.getBoundingClientRect().left - margin.left) / band)
        setHover(i >= 0 && i < points.length ? i : null)
      }}
      onClick={() => { if (hover !== null) onSelect(points[hover]!.id) }}>
      <defs>
        <pattern id={hatch} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="5" className="quarters-hatch" />
        </pattern>
      </defs>
      {yTicks.map((t) => <g key={t} className="trend-tick">
        <line x1={margin.left} x2={margin.left + innerW} y1={y(t)} y2={y(t)} />
        <text x={margin.left - 8} y={y(t)} dy="0.32em" textAnchor="end">{tickFormat(t)}</text>
      </g>)}
      {years.map((year, g) => <g key={year.label} className="quarters-year">
        {g > 0 && <line x1={margin.left + band * year.from} x2={margin.left + band * year.from} y1={margin.top - 8} y2={height - 4} />}
        <text x={(cx(year.from) + cx(year.to)) / 2} y={height - 6} textAnchor="middle">{year.label}</text>
      </g>)}
      {points.map((p, i) => {
        const h = p.value == null ? 0 : Math.max(1, (p.value / yMax) * innerH)
        const x = cx(i) - barW / 2
        const chosen = i === index
        return <g key={p.id} className={`quarters-col${chosen ? ' is-chosen' : ''}${p.complete ? '' : ' is-to-date'}${hover === i ? ' is-hot' : ''}`}
          style={{ animationDelay: `${i * 40}ms` }}>
          {h > 0 && <path d={column(x, margin.top + innerH - h, barW, h)} style={p.complete ? undefined : { fill: `url(#${hatch})` }} />}
          <text className="quarters-q" x={cx(i)} y={margin.top + innerH + 16} textAnchor="middle">{p.id.slice(5)}</text>
          {(roomy || chosen) && p.value != null && <text className="quarters-label" x={cx(i)} y={margin.top + innerH - h - 6} textAnchor="middle">{format(p.value)}</text>}
        </g>
      })}
      <line className="quarters-base" x1={margin.left} x2={margin.left + innerW} y1={margin.top + innerH} y2={margin.top + innerH} />
    </svg>}
    {hover !== null && active !== null && <div className="trend-tip" style={{ left: Math.min(Math.max(cx(active), 90), width - 90), top: Math.max(0, y(points[active]!.value ?? 0) - 12) }}>
      <span className="trend-tip-week figure-num">{quarterLabel(points[active]!.id)}, {quarterMonths(points[active]!.start, points[active]!.end)}</span>
      <strong className="figure-num">{format(points[active]!.value)}</strong>
      {toDate(points[active]!) && <span>To date: {toDate(points[active]!)}</span>}
    </div>}
  </div>
}
