import { sqlString } from './engine'
import type { OrgLevel } from './generated/org_weekly'

/** Parquet exports, each registered as a view of the same name. */
export const TABLES = {
  org_weekly: 'org_weekly.parquet',
  weekly_report: 'weekly_report.parquet',
  geo_weekly: 'geo_weekly.parquet',
  advisor_weekly: 'advisor_weekly.parquet',
  dq_weekly: 'dq_weekly.parquet',
} as const

export type Table = keyof typeof TABLES

function inList(values: readonly string[]): string {
  return values.length ? `(${values.map(sqlString).join(', ')})` : '(NULL)'
}

export function orgWeeklySql(nodeId: string, weeks: readonly string[]): string {
  return `select * from org_weekly where node_id = ${sqlString(nodeId)} and iso_week_id in ${inList(weeks)} order by iso_week_id`
}

/** Every org node at one level for a week: the map sizes district marks by activity volume. */
export function orgLevelSql(level: OrgLevel, week: string): string {
  return `select * from org_weekly where level = ${sqlString(level)} and iso_week_id = ${sqlString(week)} order by node_id`
}

/** One node's KPI rows for a week, or every child of `parentId` when that is given instead. */
export function weeklyReportSql(week: string, filter: { nodeId: string } | { parentId: string }): string {
  const where = 'nodeId' in filter ? `node_id = ${sqlString(filter.nodeId)}` : `parent_id = ${sqlString(filter.parentId)}`
  return `select * from weekly_report where iso_week_id = ${sqlString(week)} and ${where} order by node_id, kpi_code`
}

export function weeklyReportHistorySql(nodeId: string, weeks: readonly string[]): string {
  return `select * from weekly_report where node_id = ${sqlString(nodeId)} and iso_week_id in ${inList(weeks)} order by iso_week_id, kpi_code`
}

/** Every child of `parentId`, for the weeks given: the leaderboard's ranks and trends. */
export function childReportHistorySql(parentId: string, weeks: readonly string[]): string {
  return `select * from weekly_report where parent_id = ${sqlString(parentId)} and iso_week_id in ${inList(weeks)} order by iso_week_id, node_id, kpi_code`
}

export function advisorWeeklySql(branchId: string, weeks: readonly string[]): string {
  return `select * from advisor_weekly where branch_id = ${sqlString(branchId)} and iso_week_id in ${inList(weeks)} order by iso_week_id, advisor_id`
}

/** Display names of org nodes, for breadcrumbs and headings. */
export function nodeNamesSql(nodeIds: readonly string[]): string {
  return `select distinct node_id, node_name from org_weekly where node_id in ${inList(nodeIds)} order by node_id`
}

export function geoWeeklySql(week: string, districtCode?: string): string {
  const district = districtCode ? ` and district_code = ${sqlString(districtCode)}` : ''
  return `select * from geo_weekly where iso_week_id = ${sqlString(week)}${district} order by fsa_code`
}
