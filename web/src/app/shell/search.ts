import type { OrgNode } from '../../data'
import type { KpiCode } from '../../data/generated/weekly_report'

export interface Destination { id: string; label: string; kind: 'Page' | 'Region' | 'District' | 'Branch' | 'Measure'; href: string; hint?: string }

const PAGES: Destination[] = [
  { id: 'page:/', label: 'Overview', kind: 'Page', href: '/', hint: 'The national weekly briefing' },
  { id: 'page:/map', label: 'Map', kind: 'Page', href: '/map', hint: 'Regions and districts on a map of Canada' },
  { id: 'page:/pipeline', label: 'Pipeline', kind: 'Page', href: '/pipeline', hint: 'Stages, runs and where the time went' },
  { id: 'page:/quality', label: 'Data quality', kind: 'Page', href: '/quality', hint: 'Checks, rules and rows held back' },
  { id: 'page:/case-study', label: 'Case study', kind: 'Page', href: '/case-study', hint: 'How it was built' },
]

const KIND = { REGION: 'Region', DISTRICT: 'District', BRANCH: 'Branch' } as const

/** Pages, every region, district and branch with its drill URL, and every measure on the overview. */
export function destinations(nodes: readonly OrgNode[], measures: Readonly<Record<KpiCode, string>>): Destination[] {
  const byId = new Map(nodes.map((n) => [n.node_id, n]))
  const href = (node: OrgNode): string | null => {
    const chain: string[] = []
    let at: OrgNode | undefined = node
    while (at && at.level !== 'NATIONAL') { chain.unshift(at.node_id); at = at.parent_id ? byId.get(at.parent_id) : undefined }
    const segments = ['r', 'd', 'b']
    return chain.length && chain.length <= 3 ? chain.map((id, i) => `/${segments[i]}/${encodeURIComponent(id)}`).join('') : null
  }
  const org = nodes.flatMap((node): Destination[] => {
    if (node.level === 'NATIONAL') return []
    const to = href(node)
    const parent = node.parent_id ? byId.get(node.parent_id)?.node_name : undefined
    return to ? [{ id: `org:${node.node_id}`, label: node.node_name, kind: KIND[node.level], href: to, hint: parent ? `${node.node_id}, in ${parent}` : node.node_id }] : []
  })
  const kpis = (Object.entries(measures) as [KpiCode, string][]).map(([code, label]) => ({ id: `kpi:${code}`, label, kind: 'Measure' as const, href: `/?kpi=${code}`, hint: 'Plot nationally on the overview' }))
  return [...PAGES, ...org, ...kpis]
}

/**
 * Match every word of the query against the label, id and kind. Whole-label prefixes rank
 * first, then word prefixes, then anything containing the words; ties keep the listed order.
 */
export function search(all: readonly Destination[], query: string, limit = 12): Destination[] {
  const words = query.toLowerCase().trim().split(/\s+/).filter(Boolean)
  if (!words.length) return all.filter((d) => d.kind === 'Page' || d.kind === 'Region').slice(0, limit)
  const scored = all.flatMap((d, index) => {
    const label = d.label.toLowerCase()
    const hay = `${label} ${d.id.split(':')[1]!.toLowerCase()} ${d.kind.toLowerCase()} ${d.hint?.toLowerCase() ?? ''}`
    if (!words.every((w) => hay.includes(w))) return []
    const score = label.startsWith(words.join(' ')) ? 0 : words.every((w) => label.split(/[\s&()-]+/).some((part) => part.startsWith(w))) ? 1 : 2
    return [{ d, score, index }]
  })
  return scored.sort((a, b) => a.score - b.score || a.index - b.index).slice(0, limit).map((s) => s.d)
}
