import type { RunSummary } from '../../data/generated/run_log'

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  // Round once, then split, so 119.6 s reads 2 min 0 s rather than 1 min 60 s.
  if (ms < 3_600_000) {
    const seconds = Math.round(ms / 1000)
    return `${Math.floor(seconds / 60)} min ${seconds % 60} s`
  }
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
