import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { DataError } from './manifest'
import { FIXTURES, createNodeEngine, fixtureData, fixtureFetch } from './testing/fixtures'

describe('PulseData on fixtures/exports', () => {
  it('reads the manifest summary without starting the engine', async () => {
    const engine = vi.fn(createNodeEngine)
    const manifest = await fixtureData(fixtureFetch(), engine).manifest()
    expect(manifest.latest_week).toBe('2026-W40')
    expect(manifest.summary.find((k) => k.kpi_code === 'ACT_PER_ADV')?.value).toBe(11.54)
    expect(engine).not.toHaveBeenCalled()
  })

  it('returns typed org_weekly rows with plain numbers, in week order', async () => {
    const rows = await fixtureData().orgWeekly('ON', ['2026-W40', '2026-W39'])
    expect(rows.map((r) => r.iso_week_id)).toEqual(['2026-W39', '2026-W40'])
    expect(rows[0]).toMatchObject({ node_id: 'ON', level: 'REGION', parent_id: 'CA' })
    expect(typeof rows[0].active_advisors).toBe('number')
    expect(Number.isInteger(rows[0].active_advisors)).toBe(true)
  })

  it('returns a node\'s fiscal quarters with its children\'s', async () => {
    const rows = (await fixtureData().orgQuarterly('CA'))!
    expect(new Set(rows.map((r) => r.node_id))).toEqual(new Set(['CA', 'ON', 'QC']))
    const national = rows.find((r) => r.node_id === 'CA')!
    expect(national).toMatchObject({ fiscal_quarter_id: 'FY26-Q4', level: 'NATIONAL', is_complete: false, quarter_start: '2026-08-01', quarter_end: '2026-10-31' })
    expect(Number.isInteger(national.calls_out)).toBe(true)
  })

  it('leaves fiscal quarters out of an export made before the quarterly mart', async () => {
    const manifest = JSON.parse(await readFile(join(FIXTURES, 'manifest.json'), 'utf8'))
    manifest.files = manifest.files.filter((f: { name: string }) => f.name !== 'org_quarterly.parquet')
    const data = fixtureData(fixtureFetch({ 'manifest.json': () => new Response(JSON.stringify(manifest)) }))
    expect(await data.orgQuarterly('CA')).toBeNull()
  })

  it('returns one node or every child of a parent from weekly_report', async () => {
    const data = fixtureData()
    const national = await data.weeklyReport('2026-W40', { nodeId: 'CA' })
    const manifest = await data.manifest()
    expect(national.map((r) => r.kpi_code).sort()).toEqual(manifest.summary.map((k) => k.kpi_code).sort())
    const regions = await data.weeklyReport('2026-W40', { parentId: 'CA' })
    expect(new Set(regions.map((r) => r.node_id))).toEqual(new Set(['ON', 'QC']))
    expect(regions.every((r) => r.level === 'REGION')).toBe(true)
  })

  it('reads national KPI history from the fixture export in week order', async () => {
    const data = fixtureData()
    const weeks = (await data.manifest()).weeks_available
    const rows = await data.weeklyReportHistory('CA', weeks)
    expect(rows).toHaveLength(weeks.length * 12)
    expect(rows[0]?.iso_week_id).toBe(weeks[0])
    expect(rows.at(-1)).toMatchObject({ iso_week_id: '2026-W40', node_id: 'CA' })
    expect(rows.find((row) => row.kpi_code === 'LATE_RATE' && row.iso_week_id === '2026-W40')?.flag).toBe('ANOMALY')
  })

  it('filters geo_weekly by district', async () => {
    const data = fixtureData()
    const all = await data.geoWeekly('2026-W40')
    const gta = await data.geoWeekly('2026-W40', 'GTA')
    expect(gta.length).toBeGreaterThan(0)
    expect(gta.length).toBeLessThan(all.length)
    expect(gta.every((r) => r.district_code === 'GTA')).toBe(true)
  })

  it('fetches and registers each Parquet file once', async () => {
    const fetcher = fixtureFetch()
    const data = fixtureData(fetcher)
    await data.orgWeekly('ON', ['2026-W40'])
    await data.orgWeekly('QC', ['2026-W40'])
    expect(fetcher.calls.filter((url) => url.endsWith('org_weekly.parquet'))).toHaveLength(1)
  })

  it('finds a node narrative, and null for a week without one', async () => {
    const data = fixtureData()
    expect((await data.narrative('2026-W40', 'ON'))?.headline).toMatch(/^Ontario/)
    expect(await data.narrative('2026-W40', 'NOPE')).toBeNull()
    expect(await data.narrative('2026-W37', 'ON')).toBeNull()
  })

  it('reads the run log', async () => {
    const log = await fixtureData().runLog()
    expect(log.runs[0]?.run_id).toBe('weekly-2026-W40-1')
  })

  it('reads DQ rule history in week and rule order from the verified export', async () => {
    const rows = await fixtureData().dqWeekly()
    expect(rows[0]).toMatchObject({ iso_week_id: '2026-W37', rule_id: 'DQ001', action: 'QUARANTINE' })
    expect(rows.at(-1)).toMatchObject({ iso_week_id: '2026-W40', rule_id: 'DQ012' })
    expect(rows.find((row) => row.iso_week_id === '2026-W40' && row.rule_id === 'DQ010'))
      .toMatchObject({ rows_affected: 18, rows_in_batch: 175, rate: 0.1029 })
  })

  it('rejects a file whose checksum differs from the manifest', async () => {
    const real = await readFile(join(FIXTURES, 'org_weekly.parquet'))
    const tampered = new Uint8Array(real)
    tampered[tampered.length - 20] ^= 0xff
    const data = fixtureData(fixtureFetch({ 'org_weekly.parquet': () => new Response(tampered) }))
    await expect(data.orgWeekly('ON', ['2026-W40'])).rejects.toThrow(/does not match the manifest checksum/)
  })

  it('raises DataError on HTTP failure and fetches again on retry', async () => {
    let fail = true
    const data = fixtureData(fixtureFetch({
      'manifest.json': async () => (fail ? new Response('down', { status: 503 }) : new Response(await readFile(join(FIXTURES, 'manifest.json')))),
    }))
    const error = await data.manifest().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(DataError)
    expect((error as DataError).message).toBe('/data/manifest.json returned HTTP 503.')
    fail = false
    expect((await data.manifest()).run_id).toBe('weekly-2026-W40-1')
  })
})
