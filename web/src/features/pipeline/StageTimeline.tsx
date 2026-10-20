import { StatusMark } from '../../components/primitives'
import { formatDuration } from './format'
import type { NodeState, StageSummary } from './timeline'

const FLOOR_MS = 100

/** Width share on a log scale from 0.1 s to the longest stage, so seconds and hours both show. */
export function logShare(ms: number, longest: number): number {
  if (ms <= FLOOR_MS) return 0.02
  return Math.max(0.02, Math.log(ms / FLOOR_MS) / Math.log(Math.max(longest, FLOOR_MS * 10) / FLOOR_MS))
}

/**
 * Where the run's time went, one bar per stage in run order on a log scale. During a replay
 * a bar grows when its stage finishes, in step with the line diagram.
 */
export function StageTimeline({ order, labels, summaries, state, onSelect }: {
  order: readonly string[]
  labels: ReadonlyMap<string, string>
  summaries: ReadonlyMap<string, StageSummary>
  state: ReadonlyMap<string, NodeState>
  onSelect: (stage: string) => void
}) {
  const longest = Math.max(1, ...[...summaries.values()].map((s) => s.durationMs))
  const ticks = [1000, 60_000, 3_600_000].filter((t) => t <= longest * 1.5)
  return <div className="timeline">
    <div className="timeline-axis" aria-hidden="true">
      {ticks.map((t) => <span key={t} style={{ insetInlineStart: `${logShare(t, longest) * 100}%` }}>{t === 1000 ? '1 s' : t === 60_000 ? '1 min' : '1 h'}</span>)}
    </div>
    <ol>
      {order.map((stage) => {
        const summary = summaries.get(stage)
        const now = state.get(stage) ?? 'PENDING'
        const finished = now !== 'PENDING' && now !== 'RUNNING'
        return <li key={stage} className="timeline-row" data-state={now}>
          <button type="button" onClick={() => onSelect(stage)}>
            <span className="timeline-name">{labels.get(stage) ?? stage}</span>
            <span className="timeline-status">{!summary ? 'Not run' : finished ? <StatusMark status={summary.status} /> : now === 'RUNNING' ? <StatusMark status="RUNNING" /> : 'Waiting'}</span>
            <span className="timeline-track" aria-hidden="true">
              <i style={{ inlineSize: summary && finished ? `${logShare(summary.durationMs, longest) * 100}%` : '0%' }} />
              {summary && summary.attempts.length > 1 && <span className="timeline-attempts">{summary.attempts.length} attempts</span>}
            </span>
            <span className="timeline-ms figure-num">{summary && finished ? formatDuration(summary.durationMs) : '–'}</span>
          </button>
        </li>
      })}
    </ol>
    <p className="timeline-note">Log scale, so a three-hour rebuild and a one-second lock release fit on the same line.</p>
  </div>
}
