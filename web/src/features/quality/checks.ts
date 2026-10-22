import type { RunCheck, RunSummary, StageAttempt } from '../../data/generated/run_log'

/** A check drawn as a bullet: the observed value on a track, with its limits. */
export interface CheckReading {
  id: string
  title: string
  value: string
  detail: string
  /**
   * Observed value and thresholds on one scale; null when the check has no numeric limit.
   * `limit` is inclusive, as the runner applies it: a value on it passes.
   */
  bullet: { observed: number; max: number; warn?: number; fail?: number; limit?: number; unit: string } | null
}

/** What the run did around its checks. A rerun skips ingest, so the batch checks see no rows. */
export interface RunContext {
  /** Ingest skipped because every file was a duplicate (SKIPPED_DUPLICATE), not for another reason. */
  alreadyLoaded?: boolean
}

export const INGEST_SKIPPED = "Ingest skipped: this week's files were already loaded, so nothing new was checked."
/** The same, on a check card beside the sentence. */
export const INGEST_SKIPPED_SHORT = 'Ingest skipped: the files were already loaded.'

const TITLES: Record<string, string> = {
  DQ030: 'Freshness',
  DQ031: 'Activity volume',
  DQ032: 'Quarantine rate',
  DQ033: 'Defects caught',
}

const pct = (share: number, digits = 2) => `${(share * 100).toFixed(digits)}%`

/** Read a run check for display. Messages differ between runs, so every parse has a fallback. */
export function readCheck(check: RunCheck, context: RunContext = {}): CheckReading {
  const title = TITLES[check.check_id] ?? check.check_id
  const observed = check.observed
  const base = { id: check.check_id, title, detail: check.message ?? check.expected ?? '' }
  if (observed == null) return { ...base, value: '–', bullet: null }
  // A rerun of a loaded week has no batch: "0 of 0" would read as a measurement. Any other skip
  // keeps the runner's reading, since the sentence says why ingest did not run.
  if (context.alreadyLoaded &&(check.check_id === 'DQ032' || check.check_id === 'DQ033')) {
    return { ...base, value: 'No new rows', detail: INGEST_SKIPPED_SHORT, bullet: null }
  }

  if (check.check_id === 'DQ030') {
    return { ...base, value: `${observed} ${observed === 1 ? 'day' : 'days'} behind`, bullet: { observed, max: Math.max(4, observed + 1), limit: 2, unit: 'days' } }
  }
  if (check.check_id === 'DQ031') {
    const change = /change (−|-)?([\d.]+)%/.exec(check.message ?? '')
    if (change) {
      // The bullet measures size; the words keep the direction.
      const value = Number(change[2]) / 100
      return { ...base, value: `${pct(value, 1)} ${change[1] ? 'below' : 'above'} usual`, bullet: { observed: value, max: 0.1, warn: 0.05, fail: 0.5, unit: '%' } }
    }
    return { ...base, value: observed.toLocaleString('en-CA'), bullet: null }
  }
  if (check.check_id === 'DQ032') {
    // The runner reports a share (0.0003); an older run reported a percentage (0.03). A share of
    // exactly 1 would mean the whole batch was quarantined, which the run would have failed on.
    const rate = observed > 1 ? observed / 100 : observed
    return { ...base, value: pct(rate), bullet: { observed: rate, max: 0.025, limit: 0.02, unit: '%' } }
  }
  if (check.check_id === 'DQ033') {
    const injected = Number(/(\d+)/.exec(check.expected ?? '')?.[1] ?? NaN)
    const value = Number.isFinite(injected) ? `${observed.toLocaleString('en-CA')} of ${injected.toLocaleString('en-CA')}` : observed.toLocaleString('en-CA')
    return { ...base, value, bullet: null }
  }
  return { ...base, value: observed.toLocaleString('en-CA'), bullet: null }
}

const STAGE_WORDS: Record<string, string> = {
  restore_state: 'restoring state',
  generate: 'generation',
  ingest: 'ingest',
  dbt_build: 'the dbt build',
  narrate: 'narration',
  export: 'the export',
  publish_sheets: 'publishing to Sheets',
  persist_state: 'saving state',
  release_lock: 'releasing the lock',
}

/** The latest attempt of each stage, in run order. */
export function latestStages(run: RunSummary): StageAttempt[] {
  const out = new Map<string, StageAttempt>()
  for (const stage of run.stages) {
    const seen = out.get(stage.stage)
    if (!seen || stage.attempt >= seen.attempt) out.set(stage.stage, stage)
  }
  return [...out.values()]
}

/**
 * How the run's latest ingest attempt was skipped, if it was. Ingest also skips when no source files
 * exist, an upstream stage failed, or the run halted; only SKIPPED_DUPLICATE means already loaded.
 */
export function ingestSkip(run: RunSummary): { alreadyLoaded: boolean; message: string } | null {
  const ingest = latestStages(run).find((s) => s.stage === 'ingest')
  if (ingest?.status !== 'SKIPPED') return null
  const message = ingest.message ?? ''
  return { alreadyLoaded: message.includes('SKIPPED_DUPLICATE'), message }
}

/** A skip message short enough for a sentence: no local paths, no run-on detail. */
function condense(message: string): string {
  const trimmed = message.replace(/\s+under\s+\S+/g, '').replace(/\.$/, '').trim()
  const short = trimmed.charAt(0).toLowerCase() + trimmed.slice(1)
  return short.length > 90 ? `${short.slice(0, 89).trimEnd()}…` : short
}

/** "the dbt build warned on 1 test", "narration warned (1 of 5 narratives fell back to the template)". */
function stagePhrase(stage: StageAttempt): string {
  const verb = stage.status === 'FAILED' ? 'failed' : 'warned'
  const word = STAGE_WORDS[stage.stage] ?? stage.stage.replace(/_/g, ' ')
  const message = (stage.message ?? '').replace(/\.$/, '')
  if (stage.stage === 'dbt_build') {
    const count = /(\d+) (?:warned|failed|errored)/.exec(message)?.[1]
    if (count) return `${word} ${verb} on ${count} ${count === '1' ? 'test' : 'tests'}`
  }
  return message && message.length <= 70 ? `${word} ${verb} (${message.charAt(0).toLowerCase()}${message.slice(1)})` : `${word} ${verb}`
}

/** One sentence about the run's checks, any stage that warned or failed, and the rows it held back. */
export function qualitySentence(run: RunSummary): string {
  const passed = run.checks.filter((c) => c.status === 'PASS').length
  const total = run.checks.length
  const failed = run.checks.filter((c) => c.status === 'FAIL').map((c) => TITLES[c.check_id] ?? c.check_id)
  const warned = run.checks.filter((c) => c.status === 'WARN').map((c) => TITLES[c.check_id] ?? c.check_id)
  const stages = latestStages(run)
  // The checks stage is the checks themselves. Any other stage that warned or failed is why the run
  // carries that mark, so the sentence names it instead of leaving "all passed" beside a warning.
  const troubled = stages.filter((s) => s.stage !== 'checks' && (s.status === 'WARN' || s.status === 'FAILED')).map(stagePhrase).join(' and ')
  const head = total === 0
    ? `The ${run.iso_week_id} run recorded no checks${troubled ? `; ${troubled}` : ''}.`
    : passed === total
      ? `All ${total} run checks passed for ${run.iso_week_id}${troubled ? `, but ${troubled}` : ''}.`
      : `${passed} of ${total} run checks passed for ${run.iso_week_id}${failed.length ? `; ${failed.join(' and ').toLowerCase()} failed` : ''}${warned.length ? `; ${warned.join(' and ').toLowerCase()} warned` : ''}.${troubled ? ` Outside the checks, ${troubled}.` : ''}`
  const ingest = stages.find((s) => s.stage === 'ingest')
  const skip = ingestSkip(run)
  if (skip?.alreadyLoaded) return `${head} ${INGEST_SKIPPED}`
  if (skip) return `${head} Ingest was skipped${skip.message ? ` (${condense(skip.message)})` : ''}, so no new rows were loaded.`
  if (!ingest?.rows_in || ingest.rows_quarantined == null) return head
  const caught = run.checks.find((c) => c.check_id === 'DQ033')?.status === 'PASS'
  return `${head} ${ingest.rows_quarantined.toLocaleString('en-CA')} of ${ingest.rows_in.toLocaleString('en-CA')} rows were quarantined (${pct(ingest.rows_quarantined / ingest.rows_in)})${caught ? ', each one a defect the generator injected on purpose' : ''}.`
}
