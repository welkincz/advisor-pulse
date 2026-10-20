import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { fsaCoverage, basemap, bin, boundaryFeatures, drillHref, extent, fenced, historyExtent } from './data'

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

  it('reads all thirteen provinces and territories, each tagged with its serving region', () => {
    const topology = JSON.parse(readFileSync(resolve(geo, 'provinces.topo.json'), 'utf8'))
    const { provinces, borders, regionBorders } = basemap(topology)
    expect(provinces).toHaveLength(13)
    const region = Object.fromEntries(provinces.map((p) => [p.properties.province, p.properties.region_code]))
    expect(region).toMatchObject({ ON: 'ON', QC: 'QC', BC: 'WE', MB: 'WE', NS: 'AT', NL: 'AT', YT: null, NU: null })
    // Region borders are a subset of all borders: Ontario–Quebec counts, Nova Scotia–New Brunswick does not.
    expect(regionBorders.coordinates.length).toBeGreaterThan(0)
    expect(regionBorders.coordinates.length).toBeLessThan(borders.coordinates.length)
  })

  it('bins against every week in view, so a colour keeps its meaning while the weeks play', () => {
    const row = (week: string, value: number | null, kpi_code = 'SHOW_RATE') => ({ iso_week_id: week, value, kpi_code }) as never
    expect(historyExtent([row('W1', 0.8), row('W2', 0.9), row('W3', null), row('W3', 5, 'CALLS_OUT')], 'SHOW_RATE')).toEqual([0.8, 0.9])
  })

  it('drops warm-up outliers from the colour range and clamps them to the end shades', () => {
    const range = fenced([0.001, 0.05, 0.62, 0.63, 0.64, 0.64, 0.65, 0.66, 0.67])
    expect(range).toEqual([0.62, 0.67])
    expect(bin(0.001, range)).toBe(0)
    expect(bin(0.9, range)).toBe(6)
  })

  it('rolls an FSA served from two districts into one value, and keeps unknown postal codes off the map', () => {
    const row = (fsa_code: string, district_code: string, active_clients: number, clients_contacted_13w: number) =>
      ({ iso_week_id: '2026-W42', fsa_code, district_code, active_clients, clients_contacted_13w, coverage_rate_13w: clients_contacted_13w / active_clients, activities_completed: 0 })
    const { values, unknownClients } = fsaCoverage([row('V2Y', 'BCL', 1355, 790), row('V2Y', 'PRA', 3, 2), row('UNK', 'BCL', 350, 225), row('UNK', 'GTA', 605, 398), row('V6E', 'BCL', 0, 0)])
    expect(values.get('V2Y')).toBeCloseTo(792 / 1358)
    expect(values.has('UNK')).toBe(false)
    expect(values.get('V6E')).toBeNull()
    expect(unknownClients).toBe(955)
  })

  it('drills with the same region, district and week URL as the report', () => {
    expect(drillHref(null, 'ON', '2026-W39', '2026-W40')).toBe('/r/ON?week=2026-W39')
    expect(drillHref('ON', 'GTA', '2026-W40', '2026-W40')).toBe('/r/ON/d/GTA')
  })
})
