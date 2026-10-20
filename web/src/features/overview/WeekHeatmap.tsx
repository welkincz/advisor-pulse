import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { KPI_LABELS, formatKpi } from '../../data'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { settledWeeks, usualStep, versusUsual } from '../../data/usual'
import { fenced } from '../../components/primitives/scale'
import { DIVERGING } from '../../theme/tokens'
import { LOWER_IS_BETTER } from './kpis'
import { REGION_ORDER } from './RegionMultiples'

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

  const fill = (cell: WeeklyReport | undefined) => {
    const step = usualStep(deviation(cell), reach, lower)
    return step === null ? 'var(--field)' : SPLIT[step]!
  }

  return <div className="heat" ref={box}>
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
      {selected >= 0 && <rect className="heat-selected" x={labelW + selected * cellW - 1} y={-2} width={cellW + 1} height={height + 3} rx={2} />}
    </svg>}
    {hover && (() => {
      const cell = hover.row.cells.get(hover.week)
      const away = deviation(cell)
      return <div className="heat-tip" style={{ left: Math.min(Math.max(hover.x, 80), width - 80), top: hover.y }}>
        <strong>{hover.row.name}</strong>
        <span className="figure-num">{hover.week}: {formatKpi(code, cell?.value)}</span>
        {away !== null ? <span>{(Math.abs(away) * 100).toFixed(1)}% {away >= 0 ? 'above' : 'below'} its usual week</span> : <span>No usual level yet: fewer than 13 weeks of history</span>}
      </div>
    })()}
  </div>
}
