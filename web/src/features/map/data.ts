import type { Feature, FeatureCollection, MultiLineString, MultiPolygon, Polygon } from 'geojson'
import { feature, mesh } from 'topojson-client'
import { fenced } from '../../components/charts/scale'
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
