import type { Crumb } from '../../components/primitives'

export type DrillLevel = 'REGION' | 'DISTRICT' | 'BRANCH' | 'ADVISOR'

export interface DrillParams { region?: string; district?: string; branch?: string; advisor?: string }

export interface DrillPath {
  level: DrillLevel
  nodeId: string
  /** Org node ids from the region down, the current one last (an advisor is not an org node). */
  orgIds: string[]
  /** The URL of each level, without the week. */
  hrefs: string[]
  /** Segment that a child's URL adds, or null at the advisor level. */
  childSegment: 'd' | 'b' | 'a' | null
}

const LEVELS: DrillLevel[] = ['REGION', 'DISTRICT', 'BRANCH', 'ADVISOR']
const SEGMENTS = ['r', 'd', 'b', 'a'] as const

export const LEVEL_LABEL: Record<DrillLevel, string> = { REGION: 'Region', DISTRICT: 'District', BRANCH: 'Branch', ADVISOR: 'Advisor' }

export function drillPath(params: DrillParams): DrillPath | null {
  const ids = [params.region, params.district, params.branch, params.advisor]
  const depth = ids.findIndex((id) => !id)
  const known = (depth === -1 ? ids : ids.slice(0, depth)) as string[]
  if (known.length === 0) return null
  const hrefs = known.map((_, i) => known.slice(0, i + 1).map((id, j) => `/${SEGMENTS[j]}/${encodeURIComponent(id)}`).join(''))
  return {
    level: LEVELS[known.length - 1]!,
    nodeId: known.at(-1)!,
    orgIds: known.slice(0, 3),
    hrefs,
    childSegment: known.length < 4 ? SEGMENTS[known.length]! as 'd' | 'b' | 'a' : null,
  }
}

/** `?week=` when it names a week that has data and is not the latest, else nothing. */
export function weekQuery(week: string, latest: string): string {
  return week === latest ? '' : `?week=${encodeURIComponent(week)}`
}

/** The week to show: the URL's if it has data, else the latest. */
export function resolveWeek(requested: string | null, available: readonly string[]): string | undefined {
  return requested && available.includes(requested) ? requested : available.at(-1)
}

export function crumbs(path: DrillPath, names: ReadonlyMap<string, string>, query: string): Crumb[] {
  const ids = [...path.orgIds, ...(path.level === 'ADVISOR' ? [path.nodeId] : [])]
  return [
    { label: 'Canada', to: `/${query}` },
    ...ids.map((id, i) => ({ label: names.get(id) ?? id, to: `${path.hrefs[i]}${query}` })),
  ]
}
