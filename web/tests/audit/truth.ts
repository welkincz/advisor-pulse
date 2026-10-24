/**
 * The audit's ground truth: the export itself, read with DuckDB's Node binding, never through
 * the app. Every figure a page shows is compared with these rows.
 */
import { DuckDBInstance } from '@duckdb/node-api'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { AdvisorWeekly } from '../../src/data/generated/advisor_weekly'
import type { DqWeekly } from '../../src/data/generated/dq_weekly'
import type { Manifest } from '../../src/data/generated/manifest'
import type { Narrative } from '../../src/data/generated/narrative'
import type { OrgWeekly } from '../../src/data/generated/org_weekly'
import type { RunLog } from '../../src/data/generated/run_log'
import type { KpiCode, WeeklyReport } from '../../src/data/generated/weekly_report'

/** `PULSE_AUDIT_EXPORTS` points the audit at another export (the full weekly one); fixtures by default. */
export const EXPORTS = resolve(process.env.PULSE_AUDIT_EXPORTS ?? resolve(import.meta.dirname, '../../../fixtures/exports'))

export interface Path { region: string; district: string; branch: string; advisor: string }

export interface Truth {
  manifest: Manifest
  week: string
  path: Path
  /** One node's row for a measure in a week. */
  row(node: string, code: KpiCode, week?: string): WeeklyReport | undefined
  /** Every child of a node in a week, for one measure. */
  children(parent: string, code: KpiCode, week?: string): WeeklyReport[]
  advisors(branch: string, week: string): AdvisorWeekly[]
  org(node: string, week: string): OrgWeekly | undefined
  dq: DqWeekly[]
  runLog: RunLog | null
  narrative(node: string): Narrative['narratives'][number] | undefined
}

/** Numbers arrive as BigInt for integer columns; the contracts read plain numbers. */
function plain<T>(row: Record<string, unknown>): T {
  return Object.fromEntries(Object.entries(row).map(([k, v]) => [k, typeof v === 'bigint' ? Number(v) : v])) as T
}

export async function loadTruth(): Promise<Truth> {
  const manifest = JSON.parse(readFileSync(resolve(EXPORTS, 'manifest.json'), 'utf8')) as Manifest
  const week = process.env.PULSE_AUDIT_WEEK || manifest.latest_week
  if (!manifest.weeks_available.includes(week)) throw new Error(`${week} is not a week in ${EXPORTS} (${manifest.weeks_available[0]} to ${manifest.latest_week})`)
  const db = await (await DuckDBInstance.create(':memory:')).connect()
  const read = async <T>(table: string): Promise<T[]> =>
    (await db.runAndReadAll(`select * from read_parquet('${resolve(EXPORTS, `${table}.parquet`)}')`)).getRowObjectsJS().map((r) => plain<T>(r))
  const report = await read<WeeklyReport>('weekly_report')
  const advisorRows = await read<AdvisorWeekly>('advisor_weekly')
  const orgRows = await read<OrgWeekly>('org_weekly')
  const dq = await read<DqWeekly>('dq_weekly')
  const runLogFile = resolve(EXPORTS, 'run_log.json')
  const runLog = existsSync(runLogFile) ? JSON.parse(readFileSync(runLogFile, 'utf8')) as RunLog : null
  const narrativeFile = resolve(EXPORTS, `narratives/${week}.json`)
  const narratives = existsSync(narrativeFile) ? (JSON.parse(readFileSync(narrativeFile, 'utf8')) as Narrative).narratives : []

  const key = (node: string, code: string, w: string) => `${node}|${code}|${w}`
  const byKey = new Map(report.map((r) => [key(r.node_id, r.kpi_code, r.iso_week_id), r]))
  const at = (level: string, parent?: string) => [...new Set(report.filter((r) => r.level === level && r.iso_week_id === week && (!parent || r.parent_id === parent)).map((r) => r.node_id))].sort()

  // One node per level, chosen the same way on any export: the first region with a published
  // narrative this week (else the first region), its first district, branch and advisor.
  const regions = at('REGION')
  const region = regions.find((id) => narratives.some((n) => n.node_id === id)) ?? regions[0]!
  const district = at('DISTRICT', region)[0]!
  const branch = at('BRANCH', district).find((id) => advisorRows.some((a) => a.branch_id === id && a.iso_week_id === week)) ?? at('BRANCH', district)[0]!
  const advisor = advisorRows.filter((a) => a.branch_id === branch && a.iso_week_id === week).map((a) => a.advisor_id).sort()[0]!

  return {
    manifest, week, path: { region, district, branch, advisor }, dq, runLog,
    row: (node, code, w = week) => byKey.get(key(node, code, w)),
    children: (parent, code, w = week) => report.filter((r) => r.parent_id === parent && r.kpi_code === code && r.iso_week_id === w),
    advisors: (b, w) => advisorRows.filter((a) => a.branch_id === b && a.iso_week_id === w),
    org: (node, w) => orgRows.find((o) => o.node_id === node && o.iso_week_id === w),
    narrative: (node) => narratives.find((n) => n.node_id === node),
  }
}
