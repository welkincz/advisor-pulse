import type { PipelineEdge, PipelineNode } from '../../data/generated/pipeline_graph'
import type { RunSummary, StageAttempt } from '../../data/generated/run_log'

/** The replay compresses the whole run into this many milliseconds. */
export const REPLAY_MS = 6000

export type NodeState = 'PENDING' | StageAttempt['status'] | 'RUNNING'

export interface StageSummary {
  stage: string
  /** The last attempt's status. */
  status: StageAttempt['status']
  attempts: StageAttempt[]
  durationMs: number
  rowsIn: number | null
  rowsOut: number | null
  rowsQuarantined: number | null
}

/** One summary per stage, from all its attempts; rows come from the last attempt. */
export function summarize(run: RunSummary): Map<string, StageSummary> {
  const byStage = new Map<string, StageAttempt[]>()
  for (const attempt of run.stages) {
    if (!byStage.has(attempt.stage)) byStage.set(attempt.stage, [])
    byStage.get(attempt.stage)!.push(attempt)
  }
  const out = new Map<string, StageSummary>()
  for (const [stage, attempts] of byStage) {
    attempts.sort((a, b) => a.attempt - b.attempt)
    const last = attempts.at(-1)!
    out.set(stage, {
      stage,
      status: last.status,
      attempts,
      durationMs: attempts.reduce((sum, a) => sum + (a.duration_ms ?? 0), 0),
      rowsIn: last.rows_in ?? null,
      rowsOut: last.rows_out ?? null,
      rowsQuarantined: last.rows_quarantined ?? null,
    })
  }
  return out
}

export interface ReplayEvent {
  /** Milliseconds into the replay. */
  at: number
  stage: string
  state: NodeState
}

/** Each attempt starts RUNNING and ends in its status, on the run's clock scaled to `total`. */
export function replayEvents(run: RunSummary, total = REPLAY_MS): ReplayEvent[] {
  const start = Date.parse(run.started_at)
  const ends = run.stages.map((a) => Date.parse(a.ended_at ?? a.started_at))
  const end = Math.max(run.ended_at ? Date.parse(run.ended_at) : start, ...ends)
  const scale = (iso: string) => (end > start ? ((Date.parse(iso) - start) / (end - start)) * total : 0)
  const events: ReplayEvent[] = []
  for (const attempt of run.stages) {
    events.push({ at: scale(attempt.started_at), stage: attempt.stage, state: 'RUNNING' })
    events.push({ at: scale(attempt.ended_at ?? attempt.started_at), stage: attempt.stage, state: attempt.status })
  }
  // Stable: a start and end at the same instant keep that order.
  return events.map((e, i) => ({ e, i })).sort((a, b) => a.e.at - b.e.at || a.i - b.i).map(({ e }) => e)
}

/** Every stage's state once the events up to `at` have happened. */
export function stateAt(events: readonly ReplayEvent[], at: number): Map<string, NodeState> {
  const state = new Map<string, NodeState>()
  for (const event of events) {
    if (event.at > at) break
    state.set(event.stage, event.state)
  }
  return state
}

/**
 * The runner stage a graph node shows: its own, or for a SOURCE or OUTPUT node (which
 * have none) the stage that writes it.
 */
export function nodeStages(nodes: readonly PipelineNode[], edges: readonly PipelineEdge[]): Map<string, string | null> {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  return new Map(nodes.map((node) => {
    if (node.stage) return [node.id, node.stage]
    const writer = edges.map((e) => (e.target === node.id ? byId.get(e.source)?.stage : undefined)).find(Boolean)
    return [node.id, writer ?? null]
  }))
}

/** An edge carries data while the stage at its end runs (or, into a SOURCE or OUTPUT, its writer). */
export function edgeActive(edge: PipelineEdge, stages: ReadonlyMap<string, string | null>, state: ReadonlyMap<string, NodeState>): boolean {
  const stage = stages.get(edge.target)
  return stage != null && state.get(stage) === 'RUNNING'
}
