import { Link } from 'react-router-dom'
import { StatusMark } from '../../components/primitives'
import { useManifest, useRunLog } from '../../data'

/**
 * Which report this is and how the run behind it went: "Week 2026-W42, run Oct 19" with the
 * newest weekly run's status. Links to the pipeline. Nothing shows until the manifest loads.
 */
export function Freshness() {
  const manifest = useManifest()
  const runLog = useRunLog()
  if (manifest.status !== 'ready') return null
  const run = runLog.status === 'ready' ? runLog.data.runs.find((r) => r.run_type === 'WEEKLY') : undefined
  const ran = new Date(manifest.data.generated_at).toLocaleDateString('en-CA', { timeZone: 'America/Toronto', month: 'short', day: 'numeric' })
  return <Link to="/pipeline" className="freshness" title="The weekly run behind this report">
    <span className="freshness-week figure-num">{manifest.data.latest_week}</span>
    <span className="freshness-ran">run {ran}</span>
    {run && <StatusMark status={run.status} />}
  </Link>
}
