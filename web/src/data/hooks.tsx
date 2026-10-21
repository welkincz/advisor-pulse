import { type ReactNode, createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { AdvisorWeekly } from './generated/advisor_weekly'
import type { DqWeekly } from './generated/dq_weekly'
import type { GeoWeekly } from './generated/geo_weekly'
import type { Manifest } from './generated/manifest'
import type { NodeNarrative } from './generated/narrative'
import type { OrgQuarterly } from './generated/org_quarterly'
import type { OrgLevel, OrgWeekly } from './generated/org_weekly'
import type { PipelineGraph } from './generated/pipeline_graph'
import type { RunLog } from './generated/run_log'
import type { KpiCode, WeeklyReport } from './generated/weekly_report'
import type { OrgNode, PulseData } from './store'

export type DataState<T> =
  | { status: 'loading' }
  | { status: 'empty' }
  | { status: 'ready'; data: T }
  | { status: 'error'; error: Error }

export type DataResult<T> = DataState<T> & { retry: () => void }

const DataContext = createContext<PulseData | null>(null)

export function DataProvider({ data, children }: { data: PulseData; children: ReactNode }) {
  return <DataContext.Provider value={data}>{children}</DataContext.Provider>
}

export function usePulseData(): PulseData {
  const data = useContext(DataContext)
  if (!data) throw new Error('usePulseData needs a <DataProvider>.')
  return data
}

function isEmpty(value: unknown): boolean {
  return value === null || (Array.isArray(value) && value.length === 0)
}

/** Load `key` once per change of key; `load` is read from a ref so callers can pass an inline closure. */
function useData<T>(key: string, load: (data: PulseData) => Promise<T>): DataResult<T> {
  const data = usePulseData()
  const loadRef = useRef(load)
  loadRef.current = load
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<{ key: string; state: DataState<T> }>({ key, state: { status: 'loading' } })

  useEffect(() => {
    let current = true
    setState({ key, state: { status: 'loading' } })
    loadRef.current(data).then(
      (value) => current && setState({ key, state: isEmpty(value) ? { status: 'empty' } : { status: 'ready', data: value } }),
      (error: unknown) => current && setState({ key, state: { status: 'error', error: error instanceof Error ? error : new Error(String(error)) } }),
    )
    return () => { current = false }
  }, [data, key, attempt])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])
  // A key change renders once before the effect runs; never show the previous key's data.
  return { ...(state.key === key ? state.state : { status: 'loading' }), retry }
}

export function useManifest(): DataResult<Manifest> {
  return useData('manifest', (d) => d.manifest())
}

export function useRunLog(): DataResult<RunLog> {
  return useData('run_log', (d) => d.runLog())
}

export function useDqWeekly(): DataResult<DqWeekly[]> {
  return useData('dq_weekly', (d) => d.dqWeekly())
}

export function usePipelineGraph(): DataResult<PipelineGraph> {
  return useData('pipeline_graph', (d) => d.pipelineGraph())
}

export function useNarrative(week: string, nodeId: string): DataResult<NodeNarrative> {
  return useData(`narrative:${week}:${nodeId}`, (d) => d.narrative(week, nodeId)) as DataResult<NodeNarrative>
}

export function useOrgWeekly(nodeId: string, weeks: readonly string[]): DataResult<OrgWeekly[]> {
  return useData(`org:${nodeId}:${weeks.join(',')}`, (d) => d.orgWeekly(nodeId, weeks))
}

export function useOrgQuarterly(nodeId: string): DataResult<OrgQuarterly[] | null> {
  return useData(`org-quarterly:${nodeId}`, (d) => d.orgQuarterly(nodeId))
}

export function useOrgLevel(level: OrgLevel, week: string): DataResult<OrgWeekly[]> {
  return useData(`org-level:${level}:${week}`, (d) => d.orgLevel(level, week))
}

export function useWeeklyReport(week: string, filter: { nodeId: string } | { parentId: string }): DataResult<WeeklyReport[]> {
  const target = 'nodeId' in filter ? `node=${filter.nodeId}` : `parent=${filter.parentId}`
  return useData(`report:${week}:${target}`, (d) => d.weeklyReport(week, filter))
}

export function useLevelKpiHistory(level: OrgLevel, code: KpiCode): DataResult<WeeklyReport[]> {
  return useData(`level-history:${level}:${code}`, (d) => d.levelKpiHistory(level, code))
}

export function useWeeklyReportHistory(nodeId: string, weeks: readonly string[]): DataResult<WeeklyReport[]> {
  return useData(`report-history:${nodeId}:${weeks.join(',')}`, (d) => d.weeklyReportHistory(nodeId, weeks))
}

export function useChildReportHistory(parentId: string, weeks: readonly string[]): DataResult<WeeklyReport[]> {
  return useData(`child-history:${parentId}:${weeks.join(',')}`, (d) => d.childReportHistory(parentId, weeks))
}

export function useAdvisorWeekly(branchId: string, weeks: readonly string[]): DataResult<AdvisorWeekly[]> {
  return useData(`advisors:${branchId}:${weeks.join(',')}`, (d) => d.advisorWeekly(branchId, weeks))
}

export function useOrgDirectory(enabled = true): DataResult<OrgNode[]> {
  return useData(enabled ? 'org-directory' : 'org-directory-off', (d) => (enabled ? d.orgDirectory() : Promise.resolve([])))
}

export function useNodeNames(nodeIds: readonly string[]): DataResult<Map<string, string>> {
  return useData(`names:${nodeIds.join(',')}`, (d) => d.nodeNames(nodeIds))
}

export function useGeoWeekly(week: string, districtCode?: string): DataResult<GeoWeekly[]> {
  return useData(`geo:${week}:${districtCode ?? '*'}`, (d) => d.geoWeekly(week, districtCode))
}
