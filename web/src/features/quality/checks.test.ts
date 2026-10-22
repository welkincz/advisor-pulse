import { expect, it } from 'vitest'
import type { RunCheck, RunSummary } from '../../data/generated/run_log'
import { INGEST_SKIPPED, INGEST_SKIPPED_SHORT, ingestSkip, qualitySentence, readCheck } from './checks'

const check = (check_id: string, observed: number | null, expected: string, message: string, status: RunCheck['status'] = 'PASS') =>
  ({ check_id, observed, expected, message, status, severity: 'WARN' }) as RunCheck

const stage = (name: string, status: string, extra: Record<string, unknown> = {}) => ({ stage: name, status, attempt: 1, started_at: '', ...extra })

const run = (checks: RunCheck[], stages: ReturnType<typeof stage>[], status = 'SUCCESS') =>
  ({ iso_week_id: '2026-W42', status, checks, stages }) as unknown as RunSummary

const passing = [check('DQ030', 2, '', ''), check('DQ031', 1, '', ''), check('DQ032', 0, '', ''), check('DQ033', 0, '0', '')]

it('reads each run check into a value and, where it has a limit, a bullet', () => {
  expect(readCheck(check('DQ030', 2, 'lag <= 2d', 'Latest activity date: 2026-10-16'))).toMatchObject({ value: '2 days behind', bullet: { observed: 2, limit: 2 } })
  expect(readCheck(check('DQ030', 2, '', '')).bullet).not.toHaveProperty('fail')
  expect(readCheck(check('DQ031', 12171, 'within 3σ or 5%', 'adjusted 13166; trailing mean 13615, σ 202, change 3.3%'))).toMatchObject({ value: '3.3% above usual', bullet: { observed: 0.033, warn: 0.05, fail: 0.5 } })
  expect(readCheck(check('DQ032', 0.000307, '<= 2.0%', '51 of 166075'))).toMatchObject({ value: '0.03%', bullet: { limit: 0.02 } })
  expect(readCheck(check('DQ033', 51, '51 exact injected quarantines', 'Missing 0; unexpected 0'))).toMatchObject({ value: '51 of 51', bullet: null })
})

it('says the batch checks saw nothing new when ingest was skipped, instead of 0 of 0', () => {
  const skipped = { alreadyLoaded: true }
  expect(readCheck(check('DQ032', 0, '<= 2.0%', '0 of 0 batch rows quarantined'), skipped)).toMatchObject({ value: 'No new rows', detail: INGEST_SKIPPED_SHORT, bullet: null })
  expect(readCheck(check('DQ033', 0, '0 exact injected quarantines', 'Missing 0; unexpected 0'), skipped)).toMatchObject({ value: 'No new rows', bullet: null })
  // Freshness and volume read the warehouse, not the batch, so they still have a reading.
  expect(readCheck(check('DQ030', 2, '', ''), skipped)).toMatchObject({ value: '2 days behind' })
})

it('keeps the direction of a volume change in words', () => {
  expect(readCheck(check('DQ031', 9000, '', 'trailing mean 13615, change -12.4%')).value).toBe('12.4% below usual')
})

it('falls back when a message has another shape', () => {
  expect(readCheck(check('DQ031', 1.52, '|z| <= 3', '150 completed activities, z = 1.52.'))).toMatchObject({ value: '1.52', bullet: null })
  expect(readCheck(check('DQ099', null, '', ''))).toMatchObject({ title: 'DQ099', value: '–' })
})

it('says how the checks went and how many rows were held back', () => {
  const r = run([check('DQ030', 2, '', ''), check('DQ033', 51, '51', ''), check('DQ031', 1, '', '', 'WARN')], [stage('ingest', 'SUCCESS', { rows_in: 166075, rows_quarantined: 51 })], 'WARN')
  expect(qualitySentence(r)).toBe('2 of 3 run checks passed for 2026-W42; activity volume warned. 51 of 166,075 rows were quarantined (0.03%), each one a defect the generator injected on purpose.')
})

it('says all is well when every check and stage passed', () => {
  const r = run(passing, [stage('ingest', 'SUCCESS', { rows_in: 200, rows_quarantined: 3 }), stage('dbt_build', 'SUCCESS'), stage('checks', 'SUCCESS')])
  expect(qualitySentence(r)).toBe('All 4 run checks passed for 2026-W42. 3 of 200 rows were quarantined (1.50%), each one a defect the generator injected on purpose.')
})

it('names the stage that warned when every check passed, so the sentence agrees with the run mark', () => {
  const r = run(passing, [
    stage('generate', 'SKIPPED'),
    stage('ingest', 'SKIPPED', { rows_in: 0, rows_quarantined: 0, message: 'activity: SKIPPED_DUPLICATE: 106 files' }),
    stage('dbt_build', 'WARN', { message: '456 dbt nodes; 1 warned: relationships_stg_activity_booked_from_activity_id.' }),
    stage('checks', 'SUCCESS'),
    stage('export', 'RUNNING'),
  ], 'WARN')
  expect(ingestSkip(r)).toMatchObject({ alreadyLoaded: true })
  expect(qualitySentence(r)).toBe(`All 4 run checks passed for 2026-W42, but the dbt build warned on 1 test. ${INGEST_SKIPPED}`)
})

it('claims already loaded only for a duplicate skip; any other skip says why and keeps the readings', () => {
  const skippedBy = (message: string) => run(passing, [stage('ingest', 'SKIPPED', { rows_in: 0, rows_quarantined: 0, message })])
  expect(ingestSkip(skippedBy('activity: SKIPPED_DUPLICATE: 106 files; hr: SKIPPED_DUPLICATE'))).toEqual({ alreadyLoaded: true, message: expect.any(String) })

  const absent = skippedBy('No source files under /tmp/pulse/data/sources')
  expect(ingestSkip(absent)).toMatchObject({ alreadyLoaded: false })
  expect(qualitySentence(absent)).toBe('All 4 run checks passed for 2026-W42. Ingest was skipped (no source files), so no new rows were loaded.')
  expect(qualitySentence(skippedBy('Upstream stage generate failed.'))).toBe('All 4 run checks passed for 2026-W42. Ingest was skipped (upstream stage generate failed), so no new rows were loaded.')
  expect(qualitySentence(skippedBy('Run stopped at restore_state: lock held'))).toContain('Ingest was skipped (run stopped at restore_state: lock held)')
  expect(qualitySentence(absent)).not.toContain('already loaded')
  // Without a duplicate skip the page reads the checks as the runner reported them.
  expect(readCheck(check('DQ033', 0, '0 exact injected quarantines', 'Missing 0; unexpected 0'), { alreadyLoaded: false })).toMatchObject({ value: '0 of 0' })
})

it('names a stage by its message when it is short, and says when one failed', () => {
  const narrate = stage('narrate', 'WARN', { message: '1 of 5 narratives fell back to the template.' })
  expect(qualitySentence(run(passing, [narrate], 'WARN'))).toBe('All 4 run checks passed for 2026-W42, but narration warned (1 of 5 narratives fell back to the template).')
  expect(qualitySentence(run(passing, [stage('dbt_build', 'FAILED', { message: '450 dbt nodes; 3 errored: a, b, c' })], 'FAILED'))).toBe('All 4 run checks passed for 2026-W42, but the dbt build failed on 3 tests.')
})

it('names a failed check and, separately, a stage that warned', () => {
  const r = run([check('DQ030', 5, '', '', 'FAIL'), ...passing.slice(1)], [stage('narrate', 'WARN', { message: 'x'.repeat(90) })], 'FAILED')
  expect(qualitySentence(r)).toBe('3 of 4 run checks passed for 2026-W42; freshness failed. Outside the checks, narration warned.')
})

it('reads the latest attempt of a retried stage', () => {
  const r = run(passing, [stage('dbt_build', 'FAILED', { message: '1 failed' }), stage('dbt_build', 'SUCCESS', { attempt: 2 })])
  expect(qualitySentence(r)).toBe('All 4 run checks passed for 2026-W42.')
})
