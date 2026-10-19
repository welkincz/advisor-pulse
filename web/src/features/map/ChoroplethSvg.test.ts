import { expect, it } from 'vitest'
import { fitProjection, pathData } from './ChoroplethSvg'
import type { Boundary } from './data'

it('fits the bounds inside the canvas with 32 px padding', () => {
  const project = fitProjection([[-80, 43], [-74, 46]], 800, 400)
  const [x0, y0] = project([-80, 46])
  const [x1, y1] = project([-74, 43])
  expect(Math.min(x0, y0)).toBeGreaterThanOrEqual(31.9)
  expect(x1).toBeLessThanOrEqual(768.1)
  expect(y1).toBeLessThanOrEqual(368.1)
  // North is up: the northern edge has the smaller y.
  expect(y0).toBeLessThan(y1)
  // One axis is tight against the padding.
  expect(Math.abs(y0 - 32) < 0.1 || Math.abs(x0 - 32) < 0.1).toBe(true)
})

it('draws every ring of a multipolygon as a closed subpath', () => {
  const square = [[[0, 0], [1, 0], [1, 1], [0, 0]]]
  const feature = { type: 'Feature', properties: {}, geometry: { type: 'MultiPolygon', coordinates: [square, square] } } as Boundary
  const d = pathData(feature, ([x, y]) => [x! * 10, y! * 10])
  expect(d.match(/M/g)).toHaveLength(2)
  expect(d.match(/Z/g)).toHaveLength(2)
  expect(d.startsWith('M0.0 0.0L10.0 0.0')).toBe(true)
})
