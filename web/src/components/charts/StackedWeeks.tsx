import { useLayoutEffect, useRef, useState } from 'react'
import { ticks } from './scale'
import './charts.css'

export interface StackSeries { key: string; label: string; color: string; values: readonly number[] }

/**
 * Stacked weekly bars on one zero-based scale: how many rows each kind of handling took,
 * week by week. 2 px paper gaps separate segments and bars; hover shows the week's split.
 */
export function StackedWeeks({ weeks, series, label, height = 220, format = (v) => v.toLocaleString('en-CA') }: {
  weeks: readonly string[]
  series: readonly StackSeries[]
  label: string
  height?: number
  format?: (value: number) => string
}) {
  const box = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [hover, setHover] = useState<number | null>(null)
  useLayoutEffect(() => {
    const element = box.current
    if (!element) return
    setWidth(element.clientWidth)
    const observer = new ResizeObserver(() => setWidth(element.clientWidth))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const margin = { top: 12, right: 8, bottom: 24, left: 52 }
  const innerW = Math.max(0, width - margin.left - margin.right)
  const innerH = height - margin.top - margin.bottom
  const totals = weeks.map((_, i) => series.reduce((sum, s) => sum + (s.values[i] ?? 0), 0))
  const top = Math.max(1, ...totals)
  const yTicks = ticks(0, top, 3)
  const yMax = Math.max(top, yTicks.at(-1) ?? top)
  const band = innerW / Math.max(1, weeks.length)
  const barW = Math.max(1, band - (band > 4 ? 2 : 0.5))
  const y = (v: number) => margin.top + innerH - (v / yMax) * innerH
  const years = weeks.flatMap((w, i) => (i > 0 && w.slice(0, 4) !== weeks[i - 1]!.slice(0, 4) ? [{ i, label: w.slice(0, 4) }] : []))

  return <div ref={box} className="stacked" style={{ height }}>
    {width > 0 && <svg width={width} height={height} role="img" aria-label={label} onPointerLeave={() => setHover(null)}
      onPointerMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect()
        const i = Math.floor((event.clientX - rect.left - margin.left) / band)
        setHover(i >= 0 && i < weeks.length ? i : null)
      }}>
      {yTicks.map((t) => <g key={t} className="trend-tick">
        <line x1={margin.left} x2={margin.left + innerW} y1={y(t)} y2={y(t)} />
        <text x={margin.left - 8} y={y(t)} dy="0.32em" textAnchor="end">{format(t)}</text>
      </g>)}
      {years.map((year) => <g key={year.label} className="trend-year">
        <line x1={margin.left + year.i * band} x2={margin.left + year.i * band} y1={margin.top} y2={margin.top + innerH} />
        <text x={margin.left + year.i * band + 4} y={height - 6}>{year.label}</text>
      </g>)}
      {weeks.map((w, i) => {
        let base = 0
        return <g key={w} className={hover === i ? 'stacked-week is-hot' : 'stacked-week'}>
          {series.map((s) => {
            const v = s.values[i] ?? 0
            const y0 = y(base)
            base += v
            const h = y0 - y(base)
            return h > 0 ? <rect key={s.key} x={margin.left + i * band} y={y(base) + (h > 3 ? 1 : 0)} width={barW} height={Math.max(0.5, h - (h > 3 ? 1 : 0))} style={{ fill: s.color }} /> : null
          })}
        </g>
      })}
    </svg>}
    {hover !== null && <div className="trend-tip" style={{ left: Math.min(Math.max(margin.left + hover * band, 90), width - 90), top: y(totals[hover]!) - 8 }}>
      <span className="trend-tip-week figure-num">{weeks[hover]}</span>
      <strong className="figure-num">{format(totals[hover]!)}</strong>
      {series.map((s) => <span key={s.key} className="stacked-tip-row"><i style={{ background: s.color }} />{s.label} <b className="figure-num">{format(s.values[hover] ?? 0)}</b></span>)}
    </div>}
  </div>
}
