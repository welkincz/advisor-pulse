import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { bin, boundaryBounds, boundaryFeatures, drillHref, extent } from './data'

const geo = resolve(import.meta.dirname, '../../../public/geo')

describe('map geography and bins', () => {
  it('reads the shipped region, district, and FSA polygons', () => {
    for (const [name, count] of [['regions', 4], ['districts', 14], ['fsa', 122]] as const) {
      const topology = JSON.parse(readFileSync(resolve(geo, `${name}.topo.json`), 'utf8'))
      expect(boundaryFeatures(topology, name)).toHaveLength(count)
    }
  })

  it('uses seven ordered colours and reserves null for no data', () => {
    const range = extent([null, 0, 50, 100])
    expect(range).toEqual([0, 100])
    expect([bin(0, range), bin(50, range), bin(100, range), bin(null, range)]).toEqual([0, 3, 6, null])
  })

  it('fits the camera to the polygons that have data', () => {
    const topology = JSON.parse(readFileSync(resolve(geo, 'regions.topo.json'), 'utf8'))
    const features = boundaryFeatures(topology, 'regions')
    const bounds = boundaryBounds(features, new Map([['ON', 0.8], ['QC', 0.9]]), false)!
    expect(bounds[0][0]).toBeGreaterThan(-90)
    expect(bounds[1][0]).toBeLessThan(-68)
  })

  it('drills with the same region, district and week URL as the report', () => {
    expect(drillHref(null, 'ON', '2026-W39', '2026-W40')).toBe('/r/ON?week=2026-W39')
    expect(drillHref('ON', 'GTA', '2026-W40', '2026-W40')).toBe('/r/ON/d/GTA')
  })
})
