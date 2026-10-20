import type { Geometry, Position } from 'geojson'

export type Point = [number, number]
export type Box = [Point, Point]
export type Project = (position: Position) => Point

const RAD = Math.PI / 180

/**
 * Statistics Canada's Lambert conformal conic: standard parallels 49°N and 77°N, centred
 * on 91°52'W. Canada keeps its familiar shape instead of Mercator's swollen Arctic.
 * Returns unit-scale coordinates with y growing southward, like screen space.
 */
export function lambert(lat1 = 49, lat2 = 77, lat0 = 63.390675, lon0 = -91.866667): Project {
  const t = (lat: number) => Math.tan(Math.PI / 4 + (lat * RAD) / 2)
  const n = Math.log(Math.cos(lat1 * RAD) / Math.cos(lat2 * RAD)) / Math.log(t(lat2) / t(lat1))
  const f = (Math.cos(lat1 * RAD) * t(lat1) ** n) / n
  const rho0 = f / t(lat0) ** n
  return ([lon, lat]) => {
    const rho = f / t(lat!) ** n
    const theta = n * (lon! - lon0) * RAD
    return [rho * Math.sin(theta), -(rho0 - rho * Math.cos(theta))]
  }
}

function visit(coordinates: unknown, each: (position: Position) => void): void {
  if (!Array.isArray(coordinates)) return
  if (typeof coordinates[0] === 'number') each(coordinates as Position)
  else coordinates.forEach((item) => visit(item, each))
}

/** The projected bounding box of every kept position, or null when there is nothing to fit. */
export function projectedBox(geometries: readonly Geometry[], project: Project, keep: (position: Position) => boolean = () => true): Box | null {
  let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity
  for (const geometry of geometries) {
    if (!('coordinates' in geometry)) continue
    visit(geometry.coordinates, (position) => {
      if (!keep(position)) return
      const [x, y] = project(position)
      x0 = Math.min(x0, x); x1 = Math.max(x1, x)
      y0 = Math.min(y0, y); y1 = Math.max(y1, y)
    })
  }
  return Number.isFinite(x0) ? [[x0, y0], [x1, y1]] : null
}

/** Scale and offset that fit `box` into width × height with `padding` on every side. */
export function fit(box: Box, width: number, height: number, padding = 24): { k: number; x: number; y: number } {
  const [[x0, y0], [x1, y1]] = box
  const k = Math.min((width - 2 * padding) / Math.max(x1 - x0, 1e-9), (height - 2 * padding) / Math.max(y1 - y0, 1e-9))
  return { k, x: width / 2 - ((x0 + x1) / 2) * k, y: height / 2 - ((y0 + y1) / 2) * k }
}

/** A projection that maps the unit-scale `project` into a fitted screen box. */
export function fitted(project: Project, box: Box, width: number, height: number, padding?: number): Project {
  const { k, x, y } = fit(box, width, height, padding)
  return (position) => {
    const [px, py] = project(position)
    return [px * k + x, py * k + y]
  }
}

/** SVG path data for a polygon or multipolygon; each ring is a closed subpath. */
export function pathData(geometry: Geometry, project: Project): string {
  if (geometry.type !== 'Polygon' && geometry.type !== 'MultiPolygon') return ''
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
  return polygons.map((rings) => rings.map((ring) => ring.map((position, i) => {
    const [x, y] = project(position)
    return `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`
  }).join('') + 'Z').join('')).join('')
}

/** SVG path data for border lines (a TopoJSON mesh). */
export function lineData(geometry: Geometry, project: Project): string {
  if (geometry.type !== 'LineString' && geometry.type !== 'MultiLineString') return ''
  const lines = geometry.type === 'LineString' ? [geometry.coordinates] : geometry.coordinates
  return lines.map((line) => line.map((position, i) => {
    const [x, y] = project(position)
    return `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`
  }).join('')).join('')
}

/**
 * Area-weighted centroid of every outer ring, in projected space. A district is a scatter
 * of branch FSAs, so this lands in the middle of where its branches are.
 */
export function centroid(geometry: Geometry, project: Project): Point | null {
  if (geometry.type !== 'Polygon' && geometry.type !== 'MultiPolygon') return null
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
  let total = 0; let sx = 0; let sy = 0
  for (const rings of polygons) {
    const ring = rings[0]!.map(project)
    let area = 0; let cx = 0; let cy = 0
    for (let i = 0; i < ring.length - 1; i++) {
      const [ax, ay] = ring[i]!
      const [bx, by] = ring[i + 1]!
      const cross = ax * by - bx * ay
      area += cross; cx += (ax + bx) * cross; cy += (ay + by) * cross
    }
    if (Math.abs(area) < 1e-18) continue
    const weight = Math.abs(area)
    total += weight
    sx += (cx / (3 * area)) * weight
    sy += (cy / (3 * area)) * weight
  }
  return total ? [sx / total, sy / total] : null
}
