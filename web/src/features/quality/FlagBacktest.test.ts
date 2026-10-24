import { describe, expect, it } from 'vitest'
import { backtestSentence } from './FlagBacktest'
import { FLAG_BACKTEST } from './backtestResults'

describe('flag backtest', () => {
  it('states the branch anomaly result in one sentence, from the table rows', () => {
    const branch = FLAG_BACKTEST.rows.find((r) => r.rule === 'ANOMALY' && r.level === 'BRANCH')!
    const sentence = backtestSentence()
    expect(sentence).toContain(`caught ${branch.detected} of ${branch.stories} branches`)
    expect(sentence).toContain(`${branch.falsePer100} false alarms per 100 branch-weeks`)
    expect(sentence).toContain(`caught ${branch.detectedBefore} but raised ${branch.falsePer100Before}`)
    expect(sentence).not.toMatch(/live|real-time/i)
  })

  it('is empty without a branch anomaly row', () => {
    expect(backtestSentence([])).toBe('')
  })

  it('holds out a different seed from the one it tuned on', () => {
    expect(FLAG_BACKTEST.heldOutSeed).not.toBe(FLAG_BACKTEST.tunedSeed)
  })
})
