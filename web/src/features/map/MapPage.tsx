import DeckGL from '@deck.gl/react'
import { WebMercatorViewport } from '@deck.gl/core'
import { GeoJsonLayer } from '@deck.gl/layers'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Figure } from '../../components/primitives'
import { DataNotice, KPI_LABELS, formatKpi, useGeoWeekly, useManifest, useWeeklyReport } from '../../data'
import type { Manifest } from '../../data/generated/manifest'
import type { KpiCode } from '../../data/generated/weekly_report'
import { SEQUENTIAL, token, useColorScheme } from '../../theme/tokens'
import { resolveWeek } from '../drill/path'
import { type Boundary, type BoundaryProperties, bin, boundaryBounds, drillHref, extent, kpiByNode, loadBoundaries } from './data'
import './map.css'

type Shape = 'regions' | 'districts' | 'fsa'
type Rgba = [number, number, number, number]

const FALLBACK_CAMERA = { longitude: -96, latitude: 54, zoom: 2.5 }

function rgba(name: string, alpha = 255): Rgba {
  const hex = token(name).slice(1)
  return [0, 2, 4].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16)).concat(alpha) as Rgba
}

function useBoundaries(shape: Shape | null) {
  const [state, setState] = useState<{ shape: Shape; data?: Boundary[]; error?: Error } | null>(null)
  useEffect(() => {
    if (!shape) return
    let active = true
    loadBoundaries(shape).then(
      (data) => { if (active) setState({ shape, data }) },
      (error: unknown) => { if (active) setState({ shape, error: error instanceof Error ? error : new Error(String(error)) }) },
    )
    return () => { active = false }
  }, [shape])
  return state?.shape === shape ? state : null
}

function Legend({ range, code, palette }: { range: [number, number] | null; code: KpiCode; palette: Rgba[] }) {
  return <div className="map-legend" aria-label={`${KPI_LABELS[code]} colour legend`}>
    <span>{range ? formatKpi(code, range[0]) : 'No data'}</span>
    <div className="map-legend-colours" aria-hidden="true">{palette.map((_, i) => <i key={i} className={`map-swatch map-swatch-${i + 1}`} />)}</div>
    <span>{range ? formatKpi(code, range[1]) : 'No data'}</span>
    <span className="map-legend-missing">Unfilled: no data</span>
  </div>
}

function MapContent({ manifest }: { manifest: Manifest }) {
  const navigate = useNavigate()
  const [search, setSearch] = useSearchParams()
  const [code, setCode] = useState<KpiCode>('COVERAGE_13W')
  const [fsa, setFsa] = useState(false)
  const canvasRef = useRef<HTMLDivElement>(null)
  const [canvasWidth, setCanvasWidth] = useState(0)
  useEffect(() => {
    const element = canvasRef.current
    if (!element) return
    const observer = new ResizeObserver(() => setCanvasWidth(element.clientWidth))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const region = search.get('region') || null
  const week = resolveWeek(search.get('week'), manifest.weeks_available)!
  const shape: Shape = fsa && manifest.has_fsa_boundaries ? 'fsa' : region ? 'districts' : 'regions'
  const fsaMode = shape === 'fsa'
  const displayCode = fsaMode ? 'COVERAGE_13W' : code
  const regions = useBoundaries('regions')
  const boundaries = useBoundaries(shape)
  const report = useWeeklyReport(week, { parentId: region ?? 'CA' })
  const geo = useGeoWeekly(week)
  const scheme = useColorScheme()
  // The theme hook causes a render when the system scheme changes; read its active tokens.
  const palette = SEQUENTIAL.map((name) => rgba(name))
  const missing = rgba('status-neutral', 70)
  const rows = report.status === 'ready' ? report.data : []
  const byNode = kpiByNode(rows, code)
  const byFsa = new Map(geo.status === 'ready' ? geo.data.map((row) => [row.fsa_code, row.coverage_rate_13w ?? null]) : [])
  const values = fsaMode ? byFsa : byNode
  const range = extent(values.values())
  const colourKey = [...values].map(([id, value]) => `${id}:${value}`).join('|')
  const features = boundaries?.data?.filter((item) => shape !== 'districts' || item.properties.parent_id === region) ?? []
  const bounds = boundaryBounds(features, values, fsaMode)
  const fitted = bounds && canvasWidth ? new WebMercatorViewport({ width: canvasWidth, height: 432, ...FALLBACK_CAMERA }).fitBounds(bounds, { padding: 32 }) : null
  const camera = fitted ? { longitude: fitted.longitude, latitude: fitted.latitude, zoom: Math.min(8, fitted.zoom) } : FALLBACK_CAMERA
  const placeRows = regions?.data && region ? features : regions?.data ?? []
  const fsaRows = fsaMode ? [...features].sort((a, b) => {
    const left = a.properties.CFSAUID ?? ''
    const right = b.properties.CFSAUID ?? ''
    return Number(byFsa.get(right) != null) - Number(byFsa.get(left) != null) || left.localeCompare(right)
  }) : []
  const drill = (id: string) => navigate(drillHref(region, id, week, manifest.latest_week))

  const layer = new GeoJsonLayer<BoundaryProperties>({
    id: `map-${shape}-${week}-${displayCode}`,
    data: features,
    pickable: !fsaMode,
    filled: true,
    stroked: false,
    updateTriggers: { getFillColor: [colourKey, scheme] },
    getFillColor: (item) => {
      const id = fsaMode ? item.properties.CFSAUID : item.properties.node_id
      const shade = bin(id ? values.get(id) : null, range)
      return shade === null ? missing : palette[shade]!
    },
    onClick: ({ object }) => {
      if (object?.properties.node_id && !fsaMode) drill(object.properties.node_id)
    },
  })

  const setQuery = (key: string, value: string) => {
    const next = new URLSearchParams(search)
    if (!value || (key === 'week' && value === manifest.latest_week)) next.delete(key)
    else next.set(key, value)
    setSearch(next)
  }

  return <>
    <div className="map-controls">
      <label>Week <select value={week} onChange={(event) => setQuery('week', event.target.value)}>
        {[...manifest.weeks_available].reverse().map((id) => <option key={id} value={id}>{id}</option>)}
      </select></label>
      <label>Measure <select value={displayCode} disabled={fsaMode} onChange={(event) => setCode(event.target.value as KpiCode)}>
        {Object.entries(KPI_LABELS).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
      </select></label>
      <label>Area <select value={region ?? ''} onChange={(event) => { setFsa(false); setQuery('region', event.target.value) }}>
        <option value="">All regions</option>
        {regions?.data?.map((item) => <option key={item.properties.node_id} value={item.properties.node_id}>{item.properties.node_name}</option>)}
      </select></label>
      {manifest.has_fsa_boundaries && <label className="map-fsa"><input type="checkbox" checked={fsa} onChange={(event) => {
        setFsa(event.target.checked)
        if (event.target.checked && region) setQuery('region', '')
      }} /> FSA coverage layer</label>}
    </div>
    <Figure title={`${fsaMode ? 'FSA coverage' : region ? 'District' : 'Region'} map, ${week}`} reading={`${KPI_LABELS[displayCode]} by ${fsaMode ? 'FSA' : region ? 'district' : 'region'}.`} note={<>
      Boundaries adapted from <a href="https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm?year=21">Statistics Canada, 2021 Census boundary files</a> under the Statistics Canada Open Licence. No basemap tiles are used.
    </>}>
      <Legend range={range} code={displayCode} palette={palette} />
      <p className="map-scope">The map draws FSAs containing fictional branch locations. Other land is left blank.</p>
      <div className="map-layout">
        <div className="map-canvas" ref={canvasRef} aria-label={`${shape} choropleth`}>
          {boundaries?.data && (!fsaMode || geo.status === 'ready') && <DeckGL key={`${shape}-${region}-${week}-${colourKey}-${canvasWidth}`} initialViewState={camera} controller layers={[layer]} getTooltip={({ object }) => object?.properties?.node_name ?? object?.properties?.CFSAUID ?? null} />}
          {!boundaries && <p>Loading boundaries…</p>}
          {boundaries?.error && <p role="alert">{boundaries.error.message}</p>}
          {fsaMode && geo.status === 'loading' && <p>Loading FSA coverage…</p>}
          {fsaMode && geo.status === 'empty' && <p>No FSA coverage values for this week.</p>}
          {fsaMode && geo.status === 'error' && <p>FSA coverage is unavailable.</p>}
        </div>
        <div className="map-places">
          {fsaMode ? <>
            <h4>FSA coverage</h4>
            {geo.status === 'loading' && <p aria-busy="true">Loading FSA values…</p>}
            {geo.status === 'error' && <DataNotice what="FSA coverage" onRetry={geo.retry} />}
            {geo.status === 'empty' && <p>No FSA coverage values for this week.</p>}
            {geo.status === 'ready' && <div className="map-fsa-values"><table>
              <caption>13-week coverage by FSA, {week}; available values first</caption>
              <thead><tr><th scope="col">FSA</th><th scope="col">Coverage</th></tr></thead>
              <tbody>{fsaRows.map((item) => {
                const id = item.properties.CFSAUID
                return id && <tr key={id}><th scope="row">{id}</th><td>{formatKpi('COVERAGE_13W', byFsa.get(id))}</td></tr>
              })}</tbody>
            </table></div>}
          </> : <>
            <h4>{region ? 'Districts' : 'Regions'}</h4>
            <p>Select an area to open its weekly report.</p>
            {report.status === 'loading' && <p aria-busy="true">Loading map values…</p>}
            {report.status === 'error' && <DataNotice what="map values" onRetry={report.retry} />}
            <ul>{placeRows.map((item) => {
              const id = item.properties.node_id
              if (!id) return null
              return <li key={id}><button type="button" onClick={() => drill(id)}><span>{item.properties.node_name ?? id}</span><span>{formatKpi(code, byNode.get(id))}</span></button></li>
            })}</ul>
          </>}
        </div>
      </div>
    </Figure>
  </>
}

/** A lazy route: deck.gl is fetched only when the map is opened. */
export function MapPage() {
  const manifest = useManifest()
  return <main className="map-page">
    <p className="eyebrow">Maplecrest Bank · fictional</p>
    <h1>Map</h1>
    <p className="intro">Explore the weekly report by region or district. Choose an area on the map or in the list to open its report.</p>
    {manifest.status === 'loading' && <p aria-busy="true">Loading the latest weekly report…</p>}
    {manifest.status === 'error' && <DataNotice what="this week's report" onRetry={manifest.retry} />}
    {manifest.status === 'ready' && <MapContent manifest={manifest.data} />}
  </main>
}
