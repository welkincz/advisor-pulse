import { Sparkline, StatusMark } from '../../../components/primitives'
import type { RunSummary } from '../../../data/generated/run_log'
import './history.css'

function rowsOut(run: RunSummary): number | null {
  const attempts = run.stages.filter((stage) => stage.stage === 'ingest')
  return attempts.at(-1)?.rows_out ?? null
}

function duration(ms: number | null | undefined): string {
  if (ms == null) return 'Duration unavailable'
  return ms < 60_000 ? `${(ms / 1000).toFixed(1)} s` : `${(ms / 60_000).toFixed(1)} min`
}

/** Newest-first runs from the export, with a left-to-right oldest-to-newest duration trend. */
export function RunHistory({ runs, selectedId, onSelect }: {
  runs: readonly RunSummary[]
  selectedId: string
  onSelect: (runId: string) => void
}) {
  const recent = runs.slice(0, 12)
  const durations = recent.slice().reverse().map((run) => run.duration_ms ?? null)
  return <section className="pipe-history" aria-label="Run history">
    <div className="pipe-history-head">
      <div>
        <h2>Recent runs</h2>
        <p>Choose a weekly run to replay its stages.</p>
      </div>
      <div className="pipe-history-trend">
        <span>Duration, oldest to newest</span>
        <Sparkline values={durations} label="Duration of recent runs, oldest to newest" width={120} height={28} />
      </div>
    </div>
    <div className="pipe-history-list">
      {recent.map((run) => {
        const rows = rowsOut(run)
        return <button key={run.run_id} type="button" className="pipe-history-run"
          aria-pressed={run.run_id === selectedId} onClick={() => onSelect(run.run_id)}>
          <span className="pipe-history-week">{run.iso_week_id}</span>
          <StatusMark status={run.status} />
          <span className="pipe-history-stats"><span>{duration(run.duration_ms)}</span><span>{rows == null ? 'Rows unavailable' : `${rows.toLocaleString('en-CA')} rows out`}</span></span>
        </button>
      })}
    </div>
  </section>
}
