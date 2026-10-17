import { useManifest, useRunLog } from './hooks'

function formatRunTime(iso: string): string {
  return new Date(iso).toLocaleString('en-CA', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) + ' UTC'
}

/** The last weekly run time, from the manifest, or the run log when the manifest is what failed. */
function useLastRun(): string | null {
  const manifest = useManifest()
  const runLog = useRunLog()
  if (manifest.status === 'ready') return manifest.data.generated_at
  if (runLog.status === 'ready') return runLog.data.runs[0]?.ended_at ?? runLog.data.runs[0]?.started_at ?? null
  return null
}

/** A calm replacement for a section whose data could not load: what happened, when data last ran, retry. */
export function DataNotice({ onRetry, what = 'these figures' }: { onRetry?: () => void; what?: string }) {
  const lastRun = useLastRun()
  return (
    <div className="data-notice" role="status">
      <p>We could not load {what} just now.</p>
      <p className="data-notice-meta">
        {lastRun ? `Last weekly run: ${formatRunTime(lastRun)}.` : 'The last weekly run time is unavailable.'}
      </p>
      {onRetry && <button type="button" onClick={onRetry}>Try again</button>}
    </div>
  )
}
