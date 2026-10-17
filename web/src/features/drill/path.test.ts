import { describe, expect, it } from 'vitest'
import { crumbs, drillPath, resolveWeek, weekQuery } from './path'

describe('drillPath', () => {
  it('reads each level from the URL params', () => {
    expect(drillPath({ region: 'ON' })).toMatchObject({ level: 'REGION', nodeId: 'ON', childSegment: 'd', hrefs: ['/r/ON'] })
    const advisor = drillPath({ region: 'ON', district: 'GTA', branch: 'BR-0101', advisor: 'ADV-1' })!
    expect(advisor).toMatchObject({ level: 'ADVISOR', nodeId: 'ADV-1', orgIds: ['ON', 'GTA', 'BR-0101'], childSegment: null })
    expect(advisor.hrefs.at(-1)).toBe('/r/ON/d/GTA/b/BR-0101/a/ADV-1')
    expect(drillPath({})).toBeNull()
  })
})

describe('weeks', () => {
  const weeks = ['2026-W38', '2026-W39', '2026-W40']
  it('uses the URL week only when it has data', () => {
    expect(resolveWeek('2026-W39', weeks)).toBe('2026-W39')
    expect(resolveWeek('2025-W01', weeks)).toBe('2026-W40')
    expect(resolveWeek(null, weeks)).toBe('2026-W40')
  })
  it('keeps the latest week out of URLs', () => {
    expect(weekQuery('2026-W40', '2026-W40')).toBe('')
    expect(weekQuery('2026-W39', '2026-W40')).toBe('?week=2026-W39')
  })
})

describe('crumbs', () => {
  it('names each level, links every crumb, and carries the week', () => {
    const path = drillPath({ region: 'ON', district: 'GTA', branch: 'BR-0101', advisor: 'ADV-1' })!
    const names = new Map([['ON', 'Ontario'], ['GTA', 'Greater Toronto']])
    expect(crumbs(path, names, '?week=2026-W39')).toEqual([
      { label: 'Canada', to: '/?week=2026-W39' },
      { label: 'Ontario', to: '/r/ON?week=2026-W39' },
      { label: 'Greater Toronto', to: '/r/ON/d/GTA?week=2026-W39' },
      { label: 'BR-0101', to: '/r/ON/d/GTA/b/BR-0101?week=2026-W39' },
      { label: 'ADV-1', to: '/r/ON/d/GTA/b/BR-0101/a/ADV-1?week=2026-W39' },
    ])
  })
})
