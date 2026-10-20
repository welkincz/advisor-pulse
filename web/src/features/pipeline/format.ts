import type { RunSummary } from '../../data/generated/run_log'
import { summarize } from './timeline'

export function formatDuration(ms: number): string {
  // Round to the unit shown first, then choose the band from the rounded value, so a band
  // edge (59.96 s, 119.6 s, 59 min 59.6 s) moves up a unit instead of reading "60".
  if (Math.round(ms) < 1000) return `${Math.round(ms)} ms`
  const tenths = Math.round(ms / 100) / 10
  if (tenths < 60) return `${tenths.toFixed(1)} s`
  const seconds = Math.round(ms / 1000)
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ${seconds % 60} s`
  const minutes = Math.round(ms / 60_000)
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
}

/**
 * How long a run took. The export writes run_log.json while its own run is still going, so
 * that run has no duration yet; measure it to the last stage that had finished instead.
 */
export function runDuration(run: RunSummary): { ms: number; partial: boolean } | null {
  if (run.duration_ms != null) return { ms: run.duration_ms, partial: false }
  const ends = run.stages.map((s) => Date.parse(s.ended_at ?? '')).filter(Number.isFinite)
  if (!ends.length) return null
  return { ms: Math.max(...ends) - Date.parse(run.started_at), partial: true }
}

export function runTypeLabel(type: RunSummary['run_type']): string {
  return type === 'WEEKLY' ? 'Weekly' : type === 'BACKFILL' ? 'Backfill' : 'Manual'
}

/** One sentence about the newest weekly run: its outcome, how long it took, what to look at. */
export function runSentence(run: RunSummary): string {
  const took = runDuration(run)
  const outcome = { SUCCESS: 'succeeded', WARN: 'finished with a warning', FAILED: 'failed', SKIPPED: 'was skipped', RUNNING: 'is still running' }[run.status]
  const time = took && run.status !== 'RUNNING' ? ` in ${formatDuration(took.ms)}${took.partial ? ' up to the export' : ''}` : ''
  // Judge each stage by its last attempt: a failure that a retry recovered did not stop the run.
  const final = [...summarize(run).values()]
  const failed = final.find((s) => s.status === 'FAILED')
  const warned = final.filter((s) => s.status === 'WARN').map((s) => s.stage.replace('_', ' '))
  const tail = failed ? ` It stopped at ${failed.stage.replace('_', ' ')}.` : warned.length ? ` Look at ${warned.join(' and ')}.` : ''
  return `The ${runTypeLabel(run.run_type).toLowerCase()} run for ${run.iso_week_id} ${outcome}${time}.${tail}`
}
