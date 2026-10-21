import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Delta, Explain, HoverCard, type CardContent, Sparkline, Term, WeekPlayer } from '../../components/primitives'
import { DataNotice, KPI_LABELS, KPI_PLAIN, TERMS, formatKpi, happened, useChildReportHistory, useGeoWeekly, useManifest, useOrgLevel, useWeeklyReportHistory } from '../../data'
import type { Manifest } from '../../data/generated/manifest'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { REGIONS } from '../../data/regions'
import { settledWeeks } from '../../data/usual'
import { useReducedMotion } from '../../app/useReducedMotion'
import { FlipList } from '../../motion/FlipList'
import { DIVERGING, SEQUENTIAL } from '../../theme/tokens'
import { resolveWeek } from '../drill/path'
import { KPI_CODES, LOWER_IS_BETTER } from '../overview/kpis'
import { CanadaMap, type MapArea, type MapPlace } from './CanadaMap'
import { type Basemap, type Boundary, bin, standoutSentence, fsaCoverage, deviationReach, drillHref, extent, historyExtent, loadBasemap, loadBoundaries, versusUsual } from './data'
import './map.css'

// three.js loads only when the relief view is on, so the flat map stays light.
const ReliefMap = lazy(() => import('./ReliefMap'))

/** WebGL can be off (policy, old GPU, some headless browsers); then the flat map is the only view. */
function canRenderRelief(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'))
  } catch {
    return false
  }
}

// Fill colours are CSS variables, so light and dark follow tokens.css with no re-render.
const PALETTE = SEQUENTIAL.map((name) => `var(--${name})`)
const SPLIT = DIVERGING.map((name) => `var(--${name})`)

type Colouring = 'usual' | 'value'
const TREND_WEEKS = 26

function useLoaded<T>(load: (() => Promise<T>) | null, key: string) {
  const [state, setState] = useState<{ key: string; data?: T; error?: Error } | null>(null)
  const loadRef = useRef(load)
  loadRef.current = load
  useEffect(() => {
    const run = loadRef.current
    if (!run) return
    let active = true
    run().then(
      (data) => { if (active) setState({ key, data }) },
      (error: unknown) => { if (active) setState({ key, error: error instanceof Error ? error : new Error(String(error)) }) },
    )
    return () => { active = false }
  }, [key])
  return load && state?.key === key ? state : null
}

/** `usual` is the share from the area's usual week; `usualValue` that week's level; both null before 13 weeks. */
interface Row { id: string; name: string; value: number | null; wow: number | null; usual: number | null; usualValue: number | null; flag: boolean; trend: (number | null)[] }

/** One row per child node for `week`, with its trend over the weeks up to it. */
function rowsFor(history: readonly WeeklyReport[], code: KpiCode, week: string, weeks: readonly string[]): Row[] {
  const settled = settledWeeks(weeks)
  const window = weeks.slice(Math.max(0, weeks.indexOf(week) - TREND_WEEKS + 1), weeks.indexOf(week) + 1)
  const byNode = new Map<string, Map<string, WeeklyReport>>()
  for (const row of history) {
    if (row.kpi_code !== code) continue
    let weeksOf = byNode.get(row.node_id)
    if (!weeksOf) byNode.set(row.node_id, weeksOf = new Map())
    weeksOf.set(row.iso_week_id, row)
  }
  return [...byNode].map(([id, weeksOf]) => {
    const current = weeksOf.get(week)
    const any = current ?? [...weeksOf.values()][0]!
    const isSettled = Boolean(current && settled.has(week))
    return {
      id, name: any.node_name, value: current?.value ?? null, wow: current?.wow_pct ?? null,
      usual: isSettled ? versusUsual(current!) : null, usualValue: isSettled ? current!.trailing_13w_avg ?? null : null,
      flag: current?.flag === 'ANOMALY', trend: window.map((w) => weeksOf.get(w)?.value ?? null),
    }
  })
}

const percent = (value: number) => `${(value * 100).toFixed(1)}%`

function Legend({ range, reach, code, fsa }: { range: [number, number] | null; reach: number | null; code: KpiCode; fsa: boolean }) {
  return <div className="map-legend">
    {reach !== null ? <div className="map-legend-scale" aria-label={`Colour scale: worse to better than each area's 13-week average, up to ${percent(reach)}`}>
      <span>Worse <span className="figure-num">{percent(reach)}</span></span>
      <div className="map-legend-colours" aria-hidden="true">{SPLIT.map((fill, i) => <i key={i} className="map-swatch" style={{ background: fill }} />)}</div>
      <span>Better <span className="figure-num">{percent(reach)}</span></span>
      <span className="map-legend-mid">than its own <Term {...TERMS.usual}>usual week</Term>; grey is a usual week</span>
    </div> : <div className="map-legend-scale" aria-label={`${KPI_LABELS[code]} colour scale`}>
      <span className="figure-num">{range ? formatKpi(code, range[0]) : '–'}</span>
      <div className="map-legend-colours" aria-hidden="true">{PALETTE.map((_, i) => <i key={i} className={`map-swatch map-swatch-${i + 1}`} />)}</div>
      <span className="figure-num">{range ? formatKpi(code, range[1]) : '–'}</span>
      <span className="map-legend-mid"><Term title="Shade" text="Each area against its peers across every week shown, so a shade keeps its meaning while the weeks play.">across every week shown</Term></span>
    </div>}
    {!fsa && <span className="map-legend-key"><svg width="22" height="14" aria-hidden="true"><circle cx="5" cy="9" r="3" /><circle cx="15" cy="7" r="6" /></svg>Circle size: activities completed</span>}
    <span className="map-legend-key"><i className="map-legend-hatch" aria-hidden="true" />No Maplecrest branches</span>
    {!fsa && <span className="map-legend-key"><i className="map-legend-empty" aria-hidden="true" />No value this week</span>}
  </div>
}

function MapContent({ manifest }: { manifest: Manifest }) {
  const navigate = useNavigate()
  const [search, setSearch] = useSearchParams()
  const weeks = manifest.weeks_available
  const week = resolveWeek(search.get('week'), weeks)!
  const focus = search.get('region') || null
  const requested = search.get('kpi') as KpiCode | null
  const code: KpiCode = requested && KPI_CODES.includes(requested) ? requested : 'COVERAGE_13W'
  // Meeting minutes have no better direction, so they can only be coloured by value.
  const colouring: Colouring = search.get('colour') === 'value' || code === 'AVG_MEET_MIN' ? 'value' : 'usual'
  const reducedMotion = useReducedMotion()
  const [webgl] = useState(canRenderRelief)
  // Relief where it can render and motion is welcome; the flat map under reduced motion, or on request.
  const canRelief = webgl && !reducedMotion
  const relief = canRelief && search.get('view') !== 'flat'
  const [fsa, setFsa] = useState(false)
  const [hot, setHot] = useState<string | null>(null)

  const canvasRef = useRef<HTMLDivElement>(null)
  const [canvas, setCanvas] = useState({ width: 0, height: 0 })
  useEffect(() => {
    const element = canvasRef.current
    if (!element) return
    const observer = new ResizeObserver(() => setCanvas({ width: element.clientWidth, height: element.clientHeight }))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const base = useLoaded<Basemap>(loadBasemap, 'provinces')
  const districts = useLoaded<Boundary[]>(() => loadBoundaries('districts'), 'districts')
  const fsaMode = fsa && manifest.has_fsa_boundaries === true
  const [fsaAttempt, setFsaAttempt] = useState(0)
  const fsaShapes = useLoaded<Boundary[]>(fsaMode ? () => loadBoundaries('fsa') : null, fsaMode ? `fsa-${fsaAttempt}` : 'fsa-off')
  const regionHistory = useChildReportHistory('CA', weeks)
  const districtHistory = useChildReportHistory(focus ?? '', focus ? weeks : [])
  const national = useWeeklyReportHistory('CA', weeks)
  const volume = useOrgLevel('DISTRICT', week)
  const geo = useGeoWeekly(fsaMode ? week : '')

  const regionRowsAll = useMemo(() => regionHistory.status === 'ready' ? regionHistory.data : [], [regionHistory])
  const districtRowsAll = useMemo(() => districtHistory.status === 'ready' ? districtHistory.data : [], [districtHistory])
  const regionRows = useMemo(() => rowsFor(regionRowsAll, code, week, weeks), [regionRowsAll, code, week, weeks])
  const districtRows = useMemo(() => rowsFor(districtRowsAll, code, week, weeks), [districtRowsAll, code, week, weeks])
  const regionRange = useMemo(() => historyExtent(regionRowsAll, code), [regionRowsAll, code])
  const districtRange = useMemo(() => historyExtent(districtRowsAll, code), [districtRowsAll, code])
  // The diverging scale is sized from weeks that have a full 13 weeks of history behind them.
  const settled = useMemo(() => settledWeeks(weeks), [weeks])
  const regionReach = useMemo(() => deviationReach(regionRowsAll.filter((r) => settled.has(r.iso_week_id)), code), [regionRowsAll, code, settled])
  const districtReach = useMemo(() => deviationReach(districtRowsAll.filter((r) => settled.has(r.iso_week_id)), code), [districtRowsAll, code, settled])
  const regionNames = useMemo(() => new Map<string, string>([...REGIONS.map(([c, n]): [string, string] => [c, n]), ...regionRows.map((row): [string, string] => [row.id, row.name])]), [regionRows])
  const regionById = new Map(regionRows.map((row) => [row.id, row]))
  const districtById = new Map(districtRows.map((row) => [row.id, row]))
  const sizes = new Map(volume.status === 'ready' ? volume.data.map((row) => [row.node_id, row.activities_completed]) : [])
  const coverage = useMemo(() => fsaCoverage(geo.status === 'ready' ? geo.data : []), [geo])
  const geoValues = coverage.values
  const fsaRange = extent(geoValues.values())
  const fsaList = (fsaShapes?.data?.map((f) => f.properties.CFSAUID ?? '') ?? [...geoValues.keys()])
    .sort((a, b) => Number(geoValues.get(b) != null) - Number(geoValues.get(a) != null) || a.localeCompare(b))

  // Relief heights span this week's lowest to highest area; colours keep the steadier history scale.
  const weekRegionRange = extent(regionRows.map((row) => row.value))
  const weekDistrictRange = extent(districtRows.map((row) => row.value))
  /** Where a value sits in its range, 0 to 1, for relief heights; null without a value. */
  const share = (value: number | null | undefined, range: [number, number] | null) => {
    if (value == null || !range) return null
    return range[1] === range[0] ? 0.5 : Math.max(0, Math.min(1, (value - range[0]) / (range[1] - range[0])))
  }
  const shade = (value: number | null | undefined, range: [number, number] | null) => {
    const step = bin(value, range)
    return step === null ? null : PALETTE[step]!
  }
  const better = LOWER_IS_BETTER.has(code) ? 'lower' : code === 'AVG_MEET_MIN' ? 'neither' : 'higher'
  /** Blue when an area is doing better than its own usual week, brick when worse. */
  const fillOf = (row: Row | undefined, range: [number, number] | null, reach: number | null) => {
    if (!row) return null
    if (colouring === 'value' || reach === null) return shade(row.value, range)
    if (row.usual === null) return null
    const good = better === 'lower' ? -row.usual : row.usual
    return SPLIT[Math.max(-3, Math.min(3, Math.round((good / reach) * 3))) + 3]!
  }
  const places = useMemo<MapPlace[]>(() => districts?.data?.map((d) => ({
    id: d.properties.node_id ?? '', name: d.properties.node_name ?? '', region: d.properties.parent_id ?? '', geometry: d.geometry,
  })) ?? [], [districts])
  const overlay = useMemo<MapArea[] | undefined>(() => fsaMode && fsaShapes?.data
    ? fsaShapes.data.map((f) => ({ id: f.properties.CFSAUID ?? '', name: f.properties.CFSAUID ?? '', geometry: f.geometry }))
    : undefined, [fsaMode, fsaShapes])

  const playerSeries = useMemo(() => {
    if (focus) return weeks.map((w) => regionRowsAll.find((row) => row.node_id === focus && row.kpi_code === code && row.iso_week_id === w)?.value ?? null)
    const all = national.status === 'ready' ? national.data : []
    const byWeek = new Map(all.filter((row) => row.kpi_code === code).map((row) => [row.iso_week_id, row.value ?? null]))
    return weeks.map((w) => byWeek.get(w) ?? null)
  }, [focus, weeks, regionRowsAll, national, code])

  const setQuery = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(search)
    for (const [key, value] of Object.entries(changes)) {
      const fallback = key === 'week' ? manifest.latest_week : key === 'kpi' ? 'COVERAGE_13W' : key === 'colour' ? 'usual' : key === 'view' ? 'relief' : ''
      if (!value || value === fallback) next.delete(key)
      else next.set(key, value)
    }
    setSearch(next, { replace: changes.week !== undefined && Object.keys(changes).length === 1 })
  }
  const focusRegion = (region: string | null) => { setHot(null); setQuery({ region }) }
  const openDistrict = (id: string) => navigate(drillHref(focus, id, week, manifest.latest_week))

  const rows = focus ? districtRows : regionRows
  const range = focus ? districtRange : regionRange
  const reach = colouring === 'usual' ? (focus ? districtReach : regionReach) : null
  const ready = regionHistory.status === 'ready' && (!focus || districtHistory.status === 'ready')
  // A region the export does not cover still gets a row, so a gap reads as missing data, not as no region.
  const missing: Row[] = !focus && ready ? REGIONS.filter(([id]) => !regionById.has(id)).map(([id, name]) => ({ id, name, value: null, wow: null, usual: null, usualValue: null, flag: false, trend: [] })) : []
  const sorted = [...rows, ...missing].sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity))
  const top = Math.max(0, ...rows.map((row) => row.value ?? 0))
  const scope = focus ? regionNames.get(focus) ?? focus : 'Canada'
  // The readout follows the colours: in FSA mode that is 13-week coverage, whatever measure was chosen before.
  const readoutCode: KpiCode = fsaMode ? 'COVERAGE_13W' : code
  const readoutRows = focus ? regionRowsAll : national.status === 'ready' ? national.data : []
  const readout = readoutRows.find((row) => row.node_id === (focus ?? 'CA') && row.kpi_code === readoutCode && row.iso_week_id === week)?.value ?? null

  /** One card for an area, on the map and in the list: what the measure is, what happened, the trend, and the next click. */
  const cardFor = (row: Row): CardContent => ({
    title: row.name,
    value: formatKpi(code, row.value),
    what: KPI_PLAIN[code],
    happened: happened({ code, value: row.value, wow: row.wow, usual: row.usualValue, flag: row.flag, better }),
    chart: row.trend.some((v) => v != null) ? <Sparkline values={row.trend} label={`${row.name}, last ${TREND_WEEKS} weeks`} width={200} height={28} /> : undefined,
    hint: focus ? 'Click to open its weekly report.' : 'Click to fly to its districts.',
  })
  const tooltip = (id: string) => {
    if (fsaMode) return <HoverCard card={{ title: id, value: formatKpi('COVERAGE_13W', geoValues.get(id)), what: KPI_PLAIN.COVERAGE_13W }} />
    const row = districtById.get(id) ?? regionById.get(id)
    if (!row) return <HoverCard card={{ title: regionNames.get(id) ?? id, what: 'No value for this area this week.' }} />
    return <HoverCard card={cardFor(row)} />
  }

  return <>
    <div className="map-controls">
      <label>Measure <select value={fsaMode ? 'COVERAGE_13W' : code} disabled={fsaMode} onChange={(event) => setQuery({ kpi: event.target.value })}>
        {KPI_CODES.map((id) => <option key={id} value={id}>{KPI_LABELS[id]}</option>)}
      </select></label>
      <fieldset className="map-colouring" disabled={fsaMode || code === 'AVG_MEET_MIN'}>
        <legend>Colour by</legend>
        <label><input type="radio" name="colour" checked={colouring === 'usual'} onChange={() => setQuery({ colour: 'usual' })} /> Compared with usual</label>
        <label><input type="radio" name="colour" checked={colouring === 'value'} onChange={() => setQuery({ colour: 'value' })} /> Value</label>
      </fieldset>
      {canRelief && !fsaMode && <fieldset className="map-colouring">
        <legend>View</legend>
        <label><input type="radio" name="view" checked={relief} onChange={() => setQuery({ view: 'relief' })} /> Relief</label>
        <label><input type="radio" name="view" checked={!relief} onChange={() => setQuery({ view: 'flat' })} /> Flat</label>
      </fieldset>}
      {manifest.has_fsa_boundaries && <label className="map-fsa-toggle"><input type="checkbox" checked={fsa} onChange={(event) => setFsa(event.target.checked)} /> FSA coverage layer</label>}
    </div>

    <section className="map-stage" aria-label={`${KPI_LABELS[code]} map`}>
      <header className="map-readout">
        <div>
          <p className="map-readout-scope">
            {focus ? <><button type="button" className="map-back" onClick={() => focusRegion(null)}>Canada</button><span aria-hidden="true"> / </span>{scope}</> : 'Canada'}
            <span className="map-readout-week figure-num">{week}</span>
          </p>
          <p className="map-readout-value">
            <span className="figure-num">{formatKpi(readoutCode, readout)}</span>
            <span className="map-readout-kpi">{KPI_LABELS[readoutCode]}</span>
          </p>
        </div>
        {focus && <Link className="map-open" to={drillHref(null, focus, week, manifest.latest_week)}>Open the {scope} report</Link>}
      </header>
      {!fsaMode && ready && (() => {
        const sentence = standoutSentence(rows, KPI_LABELS[code], better, focus ? districtReach : regionReach)
        return sentence && <p className="map-sentence">{sentence}</p>
      })()}
      <div className="map-layout">
        <div className="map-canvas" ref={canvasRef} aria-label={`${fsaMode ? 'fsa' : focus ? 'districts' : 'regions'} map`}>
          {base?.data && districts?.data && relief && !fsaMode && <Suspense fallback={<p aria-busy="true">Raising the relief…</p>}><ReliefMap basemap={base.data} places={places}
            width={canvas.width} height={canvas.height} focus={focus} hot={hot} onHot={setHot} onRegion={focusRegion} onMark={openDistrict}
            regionNames={regionNames}
            regionFill={(id) => fillOf(regionById.get(id), regionRange, regionReach)}
            regionHeight={(id) => share(regionById.get(id)?.value, weekRegionRange)}
            regionValue={(id) => !ready ? null : regionById.get(id)?.value != null ? formatKpi(code, regionById.get(id)!.value) : 'No data'}
            mark={(id) => ({ size: sizes.get(id) ?? 0, fill: fillOf(districtById.get(id), districtRange, districtReach), label: formatKpi(code, districtById.get(id)?.value), empty: districtById.get(id)?.value == null, height: share(districtById.get(id)?.value, weekDistrictRange) })}
            tooltip={tooltip} label={`${KPI_LABELS[code]} by ${focus ? 'district' : 'province'}, ${week}, in relief: height is the value, colour the comparison. The list beside the map has every value.`} /></Suspense>}
          {base?.data && districts?.data && (!relief || fsaMode) && <CanadaMap ready={ready} basemap={base.data} width={canvas.width} height={canvas.height}
            focus={focus} regionNames={regionNames}
            regionFill={(id) => fillOf(regionById.get(id), regionRange, regionReach)}
            regionValue={(id) => !ready ? null : regionById.get(id)?.value != null ? formatKpi(code, regionById.get(id)!.value) : 'No data'}
            places={places}
            mark={(id) => ({ size: sizes.get(id) ?? 0, fill: fillOf(districtById.get(id), districtRange, districtReach), label: formatKpi(code, districtById.get(id)?.value), empty: districtById.get(id)?.value == null })}
            overlay={overlay} overlayFill={(id) => shade(geoValues.get(id), fsaRange)} hot={hot} onHot={setHot} onRegion={focusRegion} onMark={openDistrict}
            tooltip={tooltip} label={`${KPI_LABELS[code]} by ${focus ? 'district' : 'region'}, ${week}`} />}
          {(!base || !districts) && <p aria-busy="true">Drawing the map…</p>}
          {(base?.error || districts?.error) && <p role="alert">{(base?.error ?? districts?.error)!.message}</p>}
          {fsaMode && fsaShapes?.error && <p role="alert" className="map-alert">The FSA shapes could not load, so the coverage layer is not drawn. <button type="button" onClick={() => setFsaAttempt((n) => n + 1)}>Try again</button></p>}
        </div>

        <aside className="map-ranking">
          {fsaMode ? <>
            <h2>FSA coverage</h2>
            {geo.status === 'loading' && <p aria-busy="true">Loading FSA values…</p>}
            {geo.status === 'error' && <DataNotice what="FSA coverage" onRetry={geo.retry} />}
            {geo.status === 'empty' && <p>No FSA coverage values for this week.</p>}
            {geo.status === 'ready' && <div className="map-fsa-values" role="region" aria-label="FSA coverage values" tabIndex={0}><table>
              <caption>13-week coverage by FSA, {week}; available values first{coverage.unknownClients > 0 && `. ${coverage.unknownClients.toLocaleString('en-CA')} clients with an unreadable postal code are counted in their district but not mapped`}</caption>
              <thead><tr><th scope="col">FSA</th><th scope="col">Coverage</th></tr></thead>
              <tbody>{fsaList.map((id) => <tr key={id}><th scope="row">{id}</th><td>{formatKpi('COVERAGE_13W', geoValues.get(id))}</td></tr>)}</tbody>
            </table></div>}
          </> : <>
            <h2>{focus ? `Districts in ${scope}` : 'Regions'}</h2>
            <p className="map-rows-head" aria-hidden="true"><span>{KPI_LABELS[code]}</span><span>{colouring === 'usual' ? 'vs usual' : 'vs last week'}</span></p>
            {regionHistory.status === 'loading' && <p aria-busy="true">Loading map values…</p>}
            {regionHistory.status === 'error' && <DataNotice what="map values" onRetry={regionHistory.retry} />}
            {districtHistory.status === 'error' && focus && <DataNotice what="district values" onRetry={districtHistory.retry} />}
            <FlipList className="map-rows" order={sorted.map((row) => row.id)}>{sorted.map((row) => {
              // Bars start at zero, like every bar in the report; the colour carries the comparison.
              const share = row.value != null && top > 0 ? row.value / top : 0
              return <li key={row.id} data-row={row.id} className={row.id === hot ? 'is-hot' : undefined} onPointerEnter={() => setHot(row.id)} onPointerLeave={() => setHot(null)}>
                <Explain block card={() => cardFor(row)}>{(described) =>
                  <button type="button" onClick={() => focus ? openDistrict(row.id) : focusRegion(row.id)} onFocus={() => setHot(row.id)} onBlur={() => setHot(null)} {...described}>
                    <span className="map-row-name">{row.name}</span>
                    <span className="map-row-value figure-num">{formatKpi(code, row.value)}</span>
                    <span className="map-row-bar" aria-hidden="true"><i style={{ inlineSize: `${Math.max(2, share * 100)}%`, background: fillOf(row, range, reach) ?? undefined }} /></span>
                    {colouring === 'usual'
                      ? row.usual === null ? <span className="delta delta-none">No usual yet</span> : <Delta value={row.usual} better={better} against="its usual week" />
                      : <Delta value={row.wow} better={better} />}
                  </button>}</Explain>
              </li>
            })}</FlipList>
          </>}
        </aside>
      </div>
      {volume.status === 'error' && !fsaMode && <DataNotice what="district activity, which sizes the circles" onRetry={volume.retry} />}
      <Legend range={fsaMode ? fsaRange : range} reach={fsaMode ? null : reach} code={fsaMode ? 'COVERAGE_13W' : code} fsa={fsaMode} />
      <WeekPlayer weeks={weeks} value={week} onChange={(next) => setQuery({ week: next })} series={playerSeries}
        label={`Week shown on the map; the strip is ${focus ? scope : 'national'} ${KPI_LABELS[code].toLowerCase()}`} />
      <p className="map-source">
        Province shapes from <a href="https://www.naturalearthdata.com/">Natural Earth</a> (public domain); district circles sit at the middle
        of each district’s branch FSAs, adapted from <a href="https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm?year=21">Statistics Canada 2021 boundary files</a> under the Statistics Canada Open Licence.
      </p>
    </section>
  </>
}

/** A lazy route: the map code is fetched only when the map is opened. */
export function MapPage() {
  const manifest = useManifest()
  return <main className="map-page">
    <h1>Map</h1>
    <p className="intro">Where the week happened. Hover an area to see what changed; click to go deeper.</p>
    {manifest.status === 'loading' && <p aria-busy="true">Loading the latest weekly report…</p>}
    {manifest.status === 'error' && <DataNotice what="this week's report" onRetry={manifest.retry} />}
    {manifest.status === 'ready' && <MapContent manifest={manifest.data} />}
  </main>
}
