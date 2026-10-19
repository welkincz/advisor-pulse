import { Link } from 'react-router-dom'
import { useRunLog } from '../../data'
import type { Manifest } from '../../data/generated/manifest'
import type { RunLog, RunSummary } from '../../data/generated/run_log'
import './overview.css'

/** The newest run in the log when it FAILED, else null. Runs are ordered by start time, not file order. */
export function failedLatestRun(runLog: RunLog): RunSummary | null {
  const runs: RunSummary[] = [...runLog.runs]
  const latest = runs.sort((a, b) => b.started_at.localeCompare(a.started_at))[0]
  return latest?.status === 'FAILED' ? latest : null
}

/**
 * After a failed weekly run the deploy keeps the last good data and ships a new run log (#51).
 * This says so above the KPIs, which stay as they are. A missing run log shows nothing.
 */
export function RunStatusBanner({ manifest }: { manifest: Manifest }) {
  const runLog = useRunLog()
  const failed = runLog.status === 'ready' ? failedLatestRun(runLog.data) : null
  return <div role="status" className="run-status-slot">
    {failed && <div className="run-status-banner">
      <p><strong>The last weekly run failed.</strong> The run for {failed.iso_week_id} did not finish, so this page still shows the {manifest.latest_week} report from the last successful run.</p>
      <p><Link to="/pipeline">See which stage failed</Link></p>
    </div>}
  </div>
}
