import type { Geometry } from 'geojson'
import { expect, it } from 'vitest'
import { centroid, fit, fitted, lambert, pathData, projectedBox } from './projection'

const project = lambert()

it('keeps north up and west on the left in Statistics Canada Lambert', () => {
  const [vx, vy] = project([-123.1, 49.3]) // Vancouver
  const [tx, ty] = project([-79.4, 43.7]) // Toronto
  const [ix, iy] = project([-68.5, 63.7]) // Iqaluit
  expect(vx).toBeLessThan(tx)
  expect(iy).toBeLessThan(ty)
  // The central meridian is vertical: two points on it share x.
  expect(project([-91.866667, 50])[0]).toBeCloseTo(project([-91.866667, 70])[0], 9)
  // Conic, not Mercator: Vancouver sits higher on the page than Toronto though it is only 5.6° further north.
  expect(vy).toBeLessThan(ty)
  expect(ix).toBeGreaterThan(tx)
})

it('fits a box inside the canvas with padding and keeps its aspect', () => {
  const box = [[0, 0], [2, 1]] as [[number, number], [number, number]]
  const { k, x, y } = fit(box, 800, 400, 20)
  // Height binds: 360 px for one unit, centred across the width.
  expect(k).toBe(360)
  expect(0 * k + y).toBeCloseTo(20)
  expect(1 * k + y).toBeCloseTo(380)
  expect(0 * k + x).toBeCloseTo(40)
  expect(2 * k + x).toBeCloseTo(760)
})

it('can leave positions out of the fit, such as the far Arctic', () => {
  const geometry: Geometry = { type: 'MultiPoint', coordinates: [[-80, 45], [-75, 47], [-80, 82]] }
  const all = projectedBox([geometry], project)!
  const south = projectedBox([geometry], project, ([, lat]) => lat! < 74)!
  expect(south[0][1]).toBeGreaterThan(all[0][1])
  expect(projectedBox([], project)).toBeNull()
})

it('draws every ring of a multipolygon as a closed subpath', () => {
  const square = [[[0, 0], [1, 0], [1, 1], [0, 0]]]
  const d = pathData({ type: 'MultiPolygon', coordinates: [square, square] }, ([x, y]) => [x! * 10, y! * 10])
  expect(d.match(/M/g)).toHaveLength(2)
  expect(d.match(/Z/g)).toHaveLength(2)
  expect(d.startsWith('M0.0 0.0L10.0 0.0')).toBe(true)
})

it('places a scatter of polygons at their area-weighted middle', () => {
  const square = (x: number, size: number) => [[[x, 0], [x + size, 0], [x + size, size], [x, size], [x, 0]]]
  const identity = ([x, y]: number[]) => [x!, y!] as [number, number]
  const [cx] = centroid({ type: 'MultiPolygon', coordinates: [square(0, 2), square(10, 1)] }, identity)!
  // Areas 4 and 1, centres at x = 1 and 10.5: (4 × 1 + 1 × 10.5) / 5.
  expect(cx).toBeCloseTo(2.9)
  expect(centroid({ type: 'Point', coordinates: [0, 0] }, identity)).toBeNull()
  const screen = fitted(project, [[-1, -1], [1, 1]], 100, 100, 0)
  expect(screen([-91.866667, 63.390675])).toEqual([50, 50])
})
