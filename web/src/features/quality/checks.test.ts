import { expect, it } from 'vitest'
import type { RunCheck, RunSummary } from '../../data/generated/run_log'
import { qualitySentence, readCheck } from './checks'

const check = (check_id: string, observed: number | null, expected: string, message: string, status: RunCheck['status'] = 'PASS') =>
  ({ check_id, observed, expected, message, status, severity: 'WARN' }) as RunCheck

it('reads each run check into a value and, where it has a limit, a bullet', () => {
  expect(readCheck(check('DQ030', 2, 'lag <= 2d', 'Latest activity date: 2026-10-16'))).toMatchObject({ value: '2 days behind', bullet: { observed: 2, fail: 2 } })
  expect(readCheck(check('DQ031', 12171, 'within 3σ or 5%', 'adjusted 13166; trailing mean 13615, σ 202, change 3.3%'))).toMatchObject({ value: '3.3% above usual', bullet: { observed: 0.033, warn: 0.05, fail: 0.5 } })
  expect(readCheck(check('DQ032', 0.000307, '<= 2.0%', '51 of 166075'))).toMatchObject({ value: '0.03%', bullet: { fail: 0.02 } })
  expect(readCheck(check('DQ033', 51, '51 exact injected quarantines', 'Missing 0; unexpected 0'))).toMatchObject({ value: '51 of 51', bullet: null })
})

it('keeps the direction of a volume change in words', () => {
  expect(readCheck(check('DQ031', 9000, '', 'trailing mean 13615, change -12.4%')).value).toBe('12.4% below usual')
})

it('falls back when a message has another shape', () => {
  expect(readCheck(check('DQ031', 1.52, '|z| <= 3', '150 completed activities, z = 1.52.'))).toMatchObject({ value: '1.52', bullet: null })
  expect(readCheck(check('DQ099', null, '', ''))).toMatchObject({ title: 'DQ099', value: '–' })
})

it('says how the checks went and how many rows were held back', () => {
  const run = {
    iso_week_id: '2026-W42',
    checks: [check('DQ030', 2, '', ''), check('DQ033', 51, '51', ''), check('DQ031', 1, '', '', 'WARN')],
    stages: [{ stage: 'ingest', rows_in: 166075, rows_quarantined: 51 }],
  } as unknown as RunSummary
  expect(qualitySentence(run)).toBe('2 of 3 run checks passed for 2026-W42; activity volume warned. 51 of 166,075 rows were quarantined (0.03%), each one a defect the generator injected on purpose.')
})
