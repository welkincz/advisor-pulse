import type { Feature, FeatureCollection, MultiLineString, MultiPolygon, Polygon } from 'geojson'
import { feature, mesh } from 'topojson-client'
import { fenced } from '../../components/charts/scale'
import type { GeoWeekly } from '../../data/generated/geo_weekly'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'

export interface BoundaryProperties {
  node_id?: string
  node_name?: string
  parent_id?: string
  CFSAUID?: string
}

export type Boundary = Feature<Polygon | MultiPolygon, BoundaryProperties>

type Topology = Parameters<typeof feature>[0]

export function boundaryFeatures(topology: Topology, object: 'regions' | 'districts' | 'fsa'): Boundary[] {
  if (!topology.objects[object]) throw new Error(`Missing ${object} boundaries.`)
  const collection = feature(topology, topology.objects[object]) as FeatureCollection<Polygon | MultiPolygon, BoundaryProperties>
  return collection.features.filter((item) => item.geometry?.type === 'Polygon' || item.geometry?.type === 'MultiPolygon')
}

export interface ProvinceProperties {
  province: string
  name: string
  /** The Maplecrest region serving the province; null for the territories. */
  region_code: string | null
}

export type Province = Feature<Polygon | MultiPolygon, ProvinceProperties>

export interface Basemap {
  provinces: Province[]
  /** Every province border. */
  borders: MultiLineString
  /** Only the borders where the serving region changes. */
  regionBorders: MultiLineString
}

export function basemap(topology: Topology): Basemap {
  const object = topology.objects.provinces
  if (!object) throw new Error('Missing province boundaries.')
  const collection = feature(topology, object) as FeatureCollection<Polygon | MultiPolygon, ProvinceProperties>
  type Shape = Parameters<NonNullable<Parameters<typeof mesh>[2]>>[0]
  const region = (shape: Shape) => (shape.properties as Partial<ProvinceProperties> | undefined)?.region_code ?? 'none'
  return {
    provinces: collection.features,
    borders: mesh(topology, object as never, (a, b) => a !== b),
    regionBorders: mesh(topology, object as never, (a, b) => a !== b && region(a) !== region(b)),
  }
}

export async function loadBasemap(): Promise<Basemap> {
  const response = await fetch('/geo/provinces.topo.json')
  if (!response.ok) throw new Error(`Could not load the province basemap (HTTP ${response.status}).`)
  return basemap(await response.json() as Topology)
}

/**
 * Bin edges from every week in view, not just the selected one, so a colour means the same
 * value while the week player runs.
 */
export { fenced }
export { deviationReach, versusUsual } from '../../data/usual'

export function historyExtent(rows: readonly WeeklyReport[], code: KpiCode): [number, number] | null {
  return fenced(rows.filter((row) => row.kpi_code === code).map((row) => row.value ?? null))
}

export async function loadBoundaries(object: 'regions' | 'districts' | 'fsa'): Promise<Boundary[]> {
  const response = await fetch(`/geo/${object}.topo.json`)
  if (!response.ok) throw new Error(`Could not load ${object} boundaries (HTTP ${response.status}).`)
  return boundaryFeatures(await response.json() as Topology, object)
}

export function kpiByNode(rows: readonly WeeklyReport[], code: KpiCode): Map<string, number | null> {
  return new Map(rows.filter((row) => row.kpi_code === code).map((row) => [row.node_id, row.value ?? null]))
}

export function extent(values: Iterable<number | null>): [number, number] | null {
  const known = [...values].filter((value): value is number => value !== null && Number.isFinite(value))
  return known.length ? [Math.min(...known), Math.max(...known)] : null
}

export function bin(value: number | null | undefined, range: [number, number] | null): number | null {
  if (value == null || !range) return null
  const [lo, hi] = range
  return hi === lo ? 3 : Math.max(0, Math.min(6, Math.floor(((value - lo) / (hi - lo)) * 7)))
}

export function drillHref(region: string | null, nodeId: string, week: string, latest: string): string {
  const path = region ? `/r/${encodeURIComponent(region)}/d/${encodeURIComponent(nodeId)}` : `/r/${encodeURIComponent(nodeId)}`
  return `${path}${week === latest ? '' : `?week=${encodeURIComponent(week)}`}`
}

/** Clients whose postal code could not be read are filed under this FSA; it has no shape. */
export const UNKNOWN_FSA = 'UNK'

/**
 * What the FSA layer shades: the lead KPI once the week has 12 months of history behind it;
 * before that it has no value anywhere, so the layer shows activities with the area's clients,
 * as the rest of the report falls back to activities per advisor.
 */
export type FsaMeasure = 'PRTF_CONTACT_12M' | 'CLIENT_ACTIVITIES'

export interface FsaValues { measure: FsaMeasure; values: Map<string, number | null>; unknownClients: number }

/**
 * One value per FSA. geo_weekly's grain is week × district × FSA: an FSA can appear under
 * two districts when a few of its clients are served from the next district over. Sum the
 * counts across districts and divide once, so every FSA gets one honest value (taking any
 * one row lets a 3-client row overwrite a 1,355-client one).
 */
export function fsaValues(rows: readonly GeoWeekly[]): FsaValues {
  // The mart leaves the rate null on every row of a week without a full 12-month window.
  const measure: FsaMeasure = rows.some((row) => row.portfolio_contacted_rate_12m != null) ? 'PRTF_CONTACT_12M' : 'CLIENT_ACTIVITIES'
  const sums = new Map<string, { clients: number; contacted: number; activities: number }>()
  let unknownClients = 0
  for (const row of rows) {
    if (row.fsa_code === UNKNOWN_FSA) { unknownClients += row.active_clients; continue }
    const sum = sums.get(row.fsa_code) ?? { clients: 0, contacted: 0, activities: 0 }
    sum.clients += row.portfolio_clients
    sum.contacted += row.portfolio_contacted_12m
    sum.activities += row.activities_completed
    sums.set(row.fsa_code, sum)
  }
  const value = (s: { clients: number; contacted: number; activities: number }) =>
    measure === 'CLIENT_ACTIVITIES' ? s.activities : s.clients > 0 ? s.contacted / s.clients : null
  return { measure, values: new Map([...sums].map(([fsa, s]) => [fsa, value(s)])), unknownClients }
}

/**
 * One sentence on which area sat furthest from its own usual week, judged in the KPI's
 * direction, or that every area was close to usual. `reach` is the diverging scale's half-width.
 */
/** Within this share of the scale's half-width, a week counts as usual: the middle of seven steps. */
const USUAL_BAND = 1 / 6

export function standoutSentence(rows: readonly { name: string; usual: number | null }[], label: string, better: 'higher' | 'lower' | 'neither', reach: number | null): string | null {
  const known = rows.filter((r): r is { name: string; usual: number } => r.usual !== null)
  if (!known.length || !reach) return null
  const top = [...known].sort((a, b) => Math.abs(b.usual) - Math.abs(a.usual))[0]!
  if (Math.abs(top.usual) < reach * USUAL_BAND) return `Every area was within ${(reach * USUAL_BAND * 100).toFixed(1)}% of its usual week for ${label.toLowerCase()}.`
  const verdict = better === 'neither' ? '' : `, ${(better === 'lower' ? top.usual < 0 : top.usual > 0) ? 'better' : 'worse'} than usual`
  const others = known.filter((r) => r !== top && Math.sign(r.usual) === Math.sign(top.usual)).length
  const company = others === 0 ? ', the only one on that side' : others === known.length - 1 ? `; all ${known.length} areas were ${top.usual < 0 ? 'below' : 'above'} usual` : ''
  return `${top.name} sat furthest from its usual week: ${label.toLowerCase()} ${(Math.abs(top.usual) * 100).toFixed(1)}% ${top.usual < 0 ? 'below' : 'above'} its 13-week average${verdict}${company}.`
}
