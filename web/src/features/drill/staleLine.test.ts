import { describe, expect, it } from 'vitest'
import { staleBookLine } from './staleLine'

describe('staleBookLine', () => {
  it('shows the share and its 13-week move in points', () => {
    expect(staleBookLine(0.1238, 0.0112)).toEqual({ value: '12.4%', change: 'up 1.1 pts in 13 weeks' })
    expect(staleBookLine(0.2, -0.004)).toEqual({ value: '20.0%', change: 'down 0.4 pts in 13 weeks' })
  })

  it('calls a tiny move steady and leaves out a missing one', () => {
    expect(staleBookLine(0.2, 0.0004)?.change).toBe('about the same as 13 weeks earlier')
    expect(staleBookLine(0.2, null)).toEqual({ value: '20.0%', change: null })
  })

  it('has no line without a share', () => {
    expect(staleBookLine(null, 0.01)).toBeNull()
    expect(staleBookLine(undefined, undefined)).toBeNull()
  })
})
