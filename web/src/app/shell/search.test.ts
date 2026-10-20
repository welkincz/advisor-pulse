import { expect, it } from 'vitest'
import type { OrgNode } from '../../data'
import { destinations, search } from './search'

const nodes: OrgNode[] = [
  { node_id: 'CA', node_name: 'Canada', level: 'NATIONAL', parent_id: null },
  { node_id: 'BC', node_name: 'British Columbia', level: 'REGION', parent_id: 'CA' },
  { node_id: 'BCL', node_name: 'BC Lower Mainland', level: 'DISTRICT', parent_id: 'BC' },
  { node_id: 'BR-0901', node_name: 'Kitsilano Branch', level: 'BRANCH', parent_id: 'BCL' },
  { node_id: 'ON', node_name: 'Ontario', level: 'REGION', parent_id: 'CA' },
]
const all = destinations(nodes, { ACT_PER_ADV: 'Activities per advisor', SHOW_RATE: 'Show rate' } as never)

it('builds drill links for every level below national', () => {
  expect(all.find((d) => d.id === 'org:BR-0901')).toMatchObject({ kind: 'Branch', href: '/r/BC/d/BCL/b/BR-0901', hint: 'BR-0901, in BC Lower Mainland' })
  expect(all.find((d) => d.id === 'org:CA')).toBeUndefined()
  expect(all.find((d) => d.id === 'kpi:SHOW_RATE')!.href).toBe('/?kpi=SHOW_RATE')
})

it('ranks label prefixes first and matches ids and every word', () => {
  // "BC" is the region's code; its whole-label prefix match ranks the district too.
  expect(search(all, 'bc lower').map((d) => d.id)[0]).toBe('org:BCL')
  expect(search(all, 'british').map((d) => d.id)[0]).toBe('org:BC')
  expect(search(all, 'br-0901').map((d) => d.label)).toEqual(['Kitsilano Branch'])
  expect(search(all, 'show').map((d) => d.label)).toEqual(['Show rate'])
  // A district's name also finds its branches, ranked after it.
  expect(search(all, 'lower main').map((d) => d.id)).toEqual(['org:BCL', 'org:BR-0901'])
  expect(search(all, 'zzz')).toEqual([])
  expect(search(all, '').every((d) => d.kind === 'Page' || d.kind === 'Region')).toBe(true)
})
