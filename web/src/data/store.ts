import type { QueryEngine } from './engine'
import type { AdvisorWeekly } from './generated/advisor_weekly'
import type { DqWeekly } from './generated/dq_weekly'
import type { GeoWeekly } from './generated/geo_weekly'
import type { Manifest } from './generated/manifest'
import type { Narrative, NodeNarrative } from './generated/narrative'
import type { OrgLevel, OrgWeekly } from './generated/org_weekly'
import type { PipelineGraph } from './generated/pipeline_graph'
import type { RunLog } from './generated/run_log'
import type { KpiCode, WeeklyReport } from './generated/weekly_report'
import { type Fetch, fetchJson, fetchVerified, manifestFile } from './manifest'
import { TABLES, type Table, advisorWeeklySql, childReportHistorySql, geoWeeklySql, levelKpiHistorySql, nodeNamesSql, orgDirectorySql, orgLevelSql, orgWeeklySql, weeklyReportHistorySql, weeklyReportSql } from './queries'

/** An org node for search and links. */
export interface OrgNode { node_id: string; node_name: string; level: OrgLevel; parent_id: string | null }

export interface PulseDataOptions {
  /** URL prefix of the weekly export: `/data` on the site and in `make web-dev`. */
  base?: string
  fetch?: Fetch
  /** Called once, on the first query that needs SQL. */
  engine: () => Promise<QueryEngine>
}

/**
 * Everything the pages read, framework-free so the same code runs in Vitest.
 * Results are memoised per query; a failed load is forgotten so a retry fetches again.
 */
export class PulseData {
  private readonly base: string
  private readonly fetcher: Fetch
  private readonly createEngine: () => Promise<QueryEngine>
  private readonly cache = new Map<string, Promise<unknown>>()

  constructor(options: PulseDataOptions) {
    this.base = options.base ?? '/data'
    this.fetcher = options.fetch ?? ((url) => fetch(url))
    this.createEngine = options.engine
  }

  manifest(): Promise<Manifest> {
    return this.memo('manifest', () => fetchJson<Manifest>(this.fetcher, `${this.base}/manifest.json`))
  }

  /** Not in the manifest (it is written after it), so it is not checksum-verified. */
  runLog(): Promise<RunLog> {
    return this.memo('run_log', () => fetchJson<RunLog>(this.fetcher, `${this.base}/run_log.json`))
  }

  /** Checksum-verified through the manifest, like the Parquet tables. */
  pipelineGraph(): Promise<PipelineGraph> {
    return this.memo('pipeline_graph', async () => {
      const bytes = await fetchVerified(this.fetcher, this.base, manifestFile(await this.manifest(), 'pipeline_graph.json'))
      return JSON.parse(new TextDecoder().decode(bytes)) as PipelineGraph
    })
  }

  /** Null when that week has no narrative file. */
  narrative(week: string, nodeId: string): Promise<NodeNarrative | null> {
    return this.memo(`narrative:${week}:${nodeId}`, async () => {
      const file = await this.memo(`narratives:${week}`, async () => {
        const manifest = await this.manifest()
        const listed = manifest.files.find((f) => f.name === `narratives/${week}.json`)
        if (!listed) return null
        const bytes = await fetchVerified(this.fetcher, this.base, listed)
        return JSON.parse(new TextDecoder().decode(bytes)) as Narrative
      })
      return file?.narratives.find((n) => n.node_id === nodeId) ?? null
    })
  }

  orgWeekly(nodeId: string, weeks: readonly string[]): Promise<OrgWeekly[]> {
    return this.select<OrgWeekly>('org_weekly', orgWeeklySql(nodeId, weeks))
  }

  orgLevel(level: OrgLevel, week: string): Promise<OrgWeekly[]> {
    return this.select<OrgWeekly>('org_weekly', orgLevelSql(level, week))
  }

  weeklyReport(week: string, filter: { nodeId: string } | { parentId: string }): Promise<WeeklyReport[]> {
    return this.select<WeeklyReport>('weekly_report', weeklyReportSql(week, filter))
  }

  levelKpiHistory(level: OrgLevel, code: KpiCode): Promise<WeeklyReport[]> {
    return this.select<WeeklyReport>('weekly_report', levelKpiHistorySql(level, code))
  }

  weeklyReportHistory(nodeId: string, weeks: readonly string[]): Promise<WeeklyReport[]> {
    return this.select<WeeklyReport>('weekly_report', weeklyReportHistorySql(nodeId, weeks))
  }

  childReportHistory(parentId: string, weeks: readonly string[]): Promise<WeeklyReport[]> {
    return this.select<WeeklyReport>('weekly_report', childReportHistorySql(parentId, weeks))
  }

  advisorWeekly(branchId: string, weeks: readonly string[]): Promise<AdvisorWeekly[]> {
    return this.select<AdvisorWeekly>('advisor_weekly', advisorWeeklySql(branchId, weeks))
  }

  orgDirectory(): Promise<OrgNode[]> {
    return this.select<OrgNode>('org_weekly', orgDirectorySql())
  }

  async nodeNames(nodeIds: readonly string[]): Promise<Map<string, string>> {
    const rows = await this.select<{ node_id: string; node_name: string }>('org_weekly', nodeNamesSql(nodeIds))
    return new Map(rows.map((r) => [r.node_id, r.node_name]))
  }

  geoWeekly(week: string, districtCode?: string): Promise<GeoWeekly[]> {
    return this.select<GeoWeekly>('geo_weekly', geoWeeklySql(week, districtCode))
  }

  dqWeekly(): Promise<DqWeekly[]> {
    return this.select<DqWeekly>('dq_weekly', 'select * from dq_weekly order by iso_week_id, rule_id')
  }

  /** Start loading the engine early, e.g. once the first paint is done. */
  warm(): void {
    this.engine().catch(() => undefined)
  }

  private engine(): Promise<QueryEngine> {
    return this.memo('engine', this.createEngine)
  }

  private async select<T>(table: Table, sql: string): Promise<T[]> {
    return this.memo(`sql:${sql}`, async () => {
      const engine = await this.engine()
      await this.memo(`table:${table}`, async () => {
        const bytes = await fetchVerified(this.fetcher, this.base, manifestFile(await this.manifest(), TABLES[table]))
        await engine.register(table, bytes)
      })
      return (await engine.query(sql)) as T[]
    })
  }

  private memo<T>(key: string, load: () => Promise<T>): Promise<T> {
    let promise = this.cache.get(key) as Promise<T> | undefined
    if (!promise) {
      promise = load()
      this.cache.set(key, promise)
      promise.catch(() => this.cache.delete(key))
    }
    return promise
  }
}
