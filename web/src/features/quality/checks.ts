import type { RunCheck, RunSummary } from '../../data/generated/run_log'

/** A check drawn as a bullet: the observed value on a track, with its warn and fail marks. */
export interface CheckReading {
  id: string
  title: string
  value: string
  detail: string
  /** Observed value and thresholds on one scale; null when the check has no numeric limit. */
  bullet: { observed: number; max: number; warn?: number; fail?: number; unit: string } | null
}

const TITLES: Record<string, string> = {
  DQ030: 'Freshness',
  DQ031: 'Activity volume',
  DQ032: 'Quarantine rate',
  DQ033: 'Defects caught',
}

const pct = (share: number, digits = 2) => `${(share * 100).toFixed(digits)}%`

/** Read a run check for display. Messages differ between runs, so every parse has a fallback. */
export function readCheck(check: RunCheck): CheckReading {
  const title = TITLES[check.check_id] ?? check.check_id
  const observed = check.observed
  const base = { id: check.check_id, title, detail: check.message ?? check.expected ?? '' }
  if (observed == null) return { ...base, value: '–', bullet: null }

  if (check.check_id === 'DQ030') {
    return { ...base, value: `${observed} ${observed === 1 ? 'day' : 'days'} behind`, bullet: { observed, max: Math.max(4, observed + 1), fail: 2, unit: 'days' } }
  }
  if (check.check_id === 'DQ031') {
    const change = /change (−|-)?([\d.]+)%/.exec(check.message ?? '')
    if (change) {
      const value = Number(change[2]) / 100
      return { ...base, value: `${pct(value, 1)} from usual`, bullet: { observed: value, max: 0.1, warn: 0.05, fail: 0.5, unit: '%' } }
    }
    return { ...base, value: observed.toLocaleString('en-CA'), bullet: null }
  }
  if (check.check_id === 'DQ032') {
    const rate = observed > 1 ? observed / 100 : observed
    return { ...base, value: pct(rate), bullet: { observed: rate, max: 0.025, fail: 0.02, unit: '%' } }
  }
  if (check.check_id === 'DQ033') {
    const injected = Number(/(\d+)/.exec(check.expected ?? '')?.[1] ?? NaN)
    const value = Number.isFinite(injected) ? `${observed.toLocaleString('en-CA')} of ${injected.toLocaleString('en-CA')}` : observed.toLocaleString('en-CA')
    return { ...base, value, bullet: null }
  }
  return { ...base, value: observed.toLocaleString('en-CA'), bullet: null }
}

/** One sentence about the run's checks and how many rows it held back. */
export function qualitySentence(run: RunSummary): string {
  const passed = run.checks.filter((c) => c.status === 'PASS').length
  const total = run.checks.length
  const failed = run.checks.filter((c) => c.status === 'FAIL').map((c) => TITLES[c.check_id] ?? c.check_id)
  const warned = run.checks.filter((c) => c.status === 'WARN').map((c) => TITLES[c.check_id] ?? c.check_id)
  const head = total === 0
    ? `The ${run.iso_week_id} run recorded no checks.`
    : passed === total
      ? `All ${total} run checks passed for ${run.iso_week_id}.`
      : `${passed} of ${total} run checks passed for ${run.iso_week_id}${failed.length ? `; ${failed.join(' and ').toLowerCase()} failed` : ''}${warned.length ? `; ${warned.join(' and ').toLowerCase()} warned` : ''}.`
  const ingest = run.stages.filter((s) => s.stage === 'ingest').at(-1)
  if (!ingest?.rows_in || ingest.rows_quarantined == null) return head
  const caught = run.checks.find((c) => c.check_id === 'DQ033')?.status === 'PASS'
  return `${head} ${ingest.rows_quarantined.toLocaleString('en-CA')} of ${ingest.rows_in.toLocaleString('en-CA')} rows were quarantined (${pct(ingest.rows_quarantined / ingest.rows_in)})${caught ? ', each one a defect the generator injected on purpose' : ''}.`
}
