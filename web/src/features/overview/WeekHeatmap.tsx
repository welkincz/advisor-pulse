import { type KeyboardEvent, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { KPI_LABELS, formatKpi, happened } from '../../data'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { settledWeeks, usualStep, versusUsual } from '../../data/usual'
import { fenced } from '../../components/charts/scale'
import { DIVERGING } from '../../theme/tokens'
import { LOWER_IS_BETTER } from './kpis'
import { REGION_ORDER } from '../../data/regions'

const SPLIT = DIVERGING.map((name) => `var(--${name})`)
const REGION_H = 18
const DISTRICT_H = 12
const GAP = 1
const NARROW = 560

interface HeatRow { id: string; name: string; region: boolean; cells: Map<string, WeeklyReport> }

function heatRows(regions: readonly WeeklyReport[], districts: readonly WeeklyReport[]): HeatRow[] {
  const group = (rows: readonly WeeklyReport[]) => {
    const out = new Map<string, HeatRow & { parent: string }>()
    for (const row of rows) {
      let entry = out.get(row.node_id)
      if (!entry) out.set(row.node_id, entry = { id: row.node_id, name: row.node_name, region: row.level === 'REGION', parent: row.parent_id ?? '', cells: new Map() })
      entry.cells.set(row.iso_week_id, row)
    }
    return [...out.values()]
  }
  const regionRows = group(regions)
  const districtRows = group(districts)
  return REGION_ORDER.flatMap((id) => {
    const region = regionRows.find((r) => r.id === id)
    if (!region) return []
    return [region, ...districtRows.filter((d) => d.parent === id).sort((a, b) => a.name.localeCompare(b.name))]
  })
}

/**
 * Every region and district, every week, in one picture: each cell is how far that week sat
 * from the area's own 13-week average. Holidays and seasons show up as vertical bands.
 * Click a cell to open that week.
 */
export function WeekHeatmap({ regions, districts, code, weeks, week, onSelect }: {
  regions: readonly WeeklyReport[]
  districts: readonly WeeklyReport[]
  code: KpiCode
  weeks: readonly string[]
  week: string
  onSelect: (week: string) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const element = box.current
    if (!element) return
    setWidth(element.clientWidth)
    const observer = new ResizeObserver(() => setWidth(element.clientWidth))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const [hover, setHover] = useState<{ row: HeatRow; week: string; x: number; y: number } | null>(null)
  // Keyboard cursor: one tab stop for the grid, arrow keys move between cells, Enter opens the week.
  const [cursor, setCursor] = useState<{ row: number; col: number } | null>(null)

  const rows = useMemo(() => heatRows(regions, districts), [regions, districts])
  const settled = useMemo(() => settledWeeks(weeks), [weeks])
  const deviation = (cell: WeeklyReport | undefined) => (cell && settled.has(cell.iso_week_id) ? versusUsual(cell) : null)
  const reach = useMemo(() => {
    const range = fenced([...regions, ...districts].filter((r) => settled.has(r.iso_week_id)).map(versusUsual))
    return range ? Math.max(Math.abs(range[0]), Math.abs(range[1])) || null : null
  }, [regions, districts, settled])
  const lower = LOWER_IS_BETTER.has(code)
  const narrow = width < NARROW
  // On a phone the last half-year fits; on a wide screen, every week.
  const shownWeeks = narrow ? weeks.slice(-26) : weeks
  const labelW = narrow ? 92 : 168
  const cellW = Math.max(2, (width - labelW) / Math.max(1, shownWeeks.length))
  let y = 0
  const placed = rows.map((row) => {
    const h = row.region ? REGION_H : DISTRICT_H
    const top = y + (row.region && y > 0 ? 6 : 0)
    y = top + h + GAP
    return { row, top, h }
  })
  const height = y
  const selected = shownWeeks.indexOf(week)

  const cellAt = (row: number, col: number) => {
    const at = placed[row]
    const w = shownWeeks[col]
    return at && w ? { row: at.row, week: w, x: labelW + col * cellW + cellW / 2, y: at.top } : null
  }
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const now = cursor ?? { row: 0, col: Math.max(0, selected) }
    const moves: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], Home: [0, -now.col], End: [0, shownWeeks.length - 1 - now.col] }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onSelect(shownWeeks[now.col]!)
      return
    }
    const move = moves[event.key]
    if (!move) return
    event.preventDefault()
    const next = { row: Math.max(0, Math.min(placed.length - 1, now.row + move[0])), col: Math.max(0, Math.min(shownWeeks.length - 1, now.col + move[1])) }
    setCursor(next)
    setHover(cellAt(next.row, next.col))
  }
  const describe = (row: HeatRow, w: string) => {
    const cell = row.cells.get(w)
    const away = deviation(cell)
    return `${row.name}, ${w}: ${formatKpi(code, cell?.value)}${away !== null ? `, ${(Math.abs(away) * 100).toFixed(1)}% ${away >= 0 ? 'above' : 'below'} its usual week` : ''}`
  }

  const fill = (cell: WeeklyReport | undefined) => {
    const step = usualStep(deviation(cell), reach, lower)
    return step === null ? 'var(--field)' : SPLIT[step]!
  }

  return <div className="heat" ref={box} tabIndex={0} role="group" onKeyDown={onKeyDown}
    aria-label={`${KPI_LABELS[code]} by area and week. Use the arrow keys to move between cells and Enter to open a week.`}
    onFocus={() => { if (!cursor) { const start = { row: 0, col: Math.max(0, selected) }; setCursor(start); setHover(cellAt(start.row, start.col)) } }}
    onBlur={() => { setCursor(null); setHover(null) }}>
    <p className="heat-live" aria-live="polite">{cursor && hover ? describe(hover.row, hover.week) : ''}</p>
    {width > 0 && <svg width={width} height={height + 22} role="img" className="heat-svg"
      aria-label={`${KPI_LABELS[code]} for ${rows.length} regions and districts over ${shownWeeks.length} weeks, coloured by distance from each area's own 13-week average`}
      onPointerLeave={() => setHover(null)}>
      {placed.map(({ row, top, h }) => <g key={row.id} className={row.region ? 'heat-region' : 'heat-district'}>
        <text x={row.region ? 0 : 10} y={top + h / 2} dy="0.35em" className="heat-label">{narrow && !row.region ? row.id : row.name}</text>
        {shownWeeks.map((w, i) => {
          const cell = row.cells.get(w)
          return <rect key={w} x={labelW + i * cellW} y={top} width={Math.max(1, cellW - GAP)} height={h} rx={1}
            style={{ fill: fill(cell), transitionDelay: `${i * 4}ms` }}
            onPointerEnter={() => setHover({ row, week: w, x: labelW + i * cellW + cellW / 2, y: top })}
            onClick={() => onSelect(w)} />
        })}
      </g>)}
      {shownWeeks.map((w, i) => i > 0 && w.slice(0, 4) !== shownWeeks[i - 1]!.slice(0, 4)
        ? <g key={w} className="heat-year"><line x1={labelW + i * cellW - 0.5} x2={labelW + i * cellW - 0.5} y1={0} y2={height} /><text x={labelW + i * cellW + 3} y={height + 14}>{w.slice(0, 4)}</text></g>
        : null)}
      {cursor && <rect className="heat-cursor" x={labelW + cursor.col * cellW - 1} y={placed[cursor.row]!.top - 1} width={cellW + 1} height={placed[cursor.row]!.h + 2} rx={2} />}
      {selected >= 0 && <rect className="heat-selected" x={labelW + selected * cellW - 1} y={-2} width={cellW + 1} height={height + 3} rx={2} />}
    </svg>}
    {hover && (() => {
      const cell = hover.row.cells.get(hover.week)
      const away = deviation(cell)
      const better = code === 'AVG_MEET_MIN' ? 'neither' : lower ? 'lower' : 'higher'
      return <div className="heat-tip" style={{ left: Math.min(Math.max(hover.x, 120), width - 120), top: hover.y }}>
        <strong>{hover.row.name}</strong>
        <span className="figure-num">{hover.week}: {formatKpi(code, cell?.value)}</span>
        {happened({ code, value: cell?.value, wow: cell?.wow_pct, usual: away === null ? null : cell?.trailing_13w_avg, flag: cell?.flag === 'ANOMALY', better })
          .map((line) => <span key={line} className="heat-tip-line">{line}</span>)}
        <span className="heat-tip-hint">Click to open this week</span>
      </div>
    })()}
  </div>
}
