import type { Feature, FeatureCollection, MultiPolygon, Polygon } from 'geojson'
import { feature } from 'topojson-client'
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
  return hi === lo ? 3 : Math.min(6, Math.floor(((value - lo) / (hi - lo)) * 7))
}

/** Bounds of the actual data-bearing polygons; fall back to every boundary. */
export function boundaryBounds(features: readonly Boundary[], values: ReadonlyMap<string, number | null>, fsa: boolean): [[number, number], [number, number]] | null {
  const selected = features.filter((item) => {
    const id = fsa ? item.properties.CFSAUID : item.properties.node_id
    return id && values.get(id) != null
  })
  const visible = selected.length ? selected : features
  let west = Infinity; let south = Infinity; let east = -Infinity; let north = -Infinity
  const visit = (value: unknown) => {
    if (!Array.isArray(value)) return
    if (typeof value[0] === 'number' && typeof value[1] === 'number') {
      west = Math.min(west, value[0]); east = Math.max(east, value[0])
      south = Math.min(south, value[1]); north = Math.max(north, value[1])
    } else value.forEach(visit)
  }
  visible.forEach((item) => visit(item.geometry.coordinates))
  return Number.isFinite(west) ? [[west, south], [east, north]] : null
}

export function drillHref(region: string | null, nodeId: string, week: string, latest: string): string {
  const path = region ? `/r/${encodeURIComponent(region)}/d/${encodeURIComponent(nodeId)}` : `/r/${encodeURIComponent(nodeId)}`
  return `${path}${week === latest ? '' : `?week=${encodeURIComponent(week)}`}`
}
