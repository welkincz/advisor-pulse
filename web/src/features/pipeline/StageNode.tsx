import { Handle, type Node, type NodeProps, Position } from '@xyflow/react'
import { StatusMark } from '../../components/primitives'
import type { PipelineNodeKind } from '../../data/generated/pipeline_graph'
import type { NodeState, StageSummary } from './timeline'

export type StageNodeData = {
  label: string
  kind: PipelineNodeKind
  state: NodeState | null
  summary: StageSummary | null
}
export type StageFlowNode = Node<StageNodeData, 'stage'>

const KIND: Record<PipelineNodeKind, string> = { SOURCE: 'Source', STAGE: 'Stage', DBT_LAYER: 'dbt layer', OUTPUT: 'Output' }

export function formatDuration(ms: number): string {
  return ms < 1000 ? `${ms} ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`
}

function count(value: number | null): string {
  return value === null ? '–' : value.toLocaleString('en-CA')
}

/** One graph node: kind, label, status, and for a stage its rows, duration and attempts. */
export function StageNode({ data, selected }: NodeProps<StageFlowNode>) {
  const { label, kind, state, summary } = data
  // A stage that has not started yet in the replay shows no figures.
  const settled = state !== null && state !== 'PENDING' && state !== 'RUNNING'
  return <div className={`pipe-node pipe-node-${kind.toLowerCase()}${selected ? ' is-selected' : ''}`} data-state={state ?? 'NONE'}>
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <span className="pipe-kind">{KIND[kind]}</span>
    <span className="pipe-label">{label}</span>
    {state && state !== 'PENDING' && <StatusMark status={state} />}
    {state === 'PENDING' && <span className="pipe-pending">Waiting</span>}
    {kind === 'STAGE' && summary && settled && <span className="pipe-meta">
      {formatDuration(summary.durationMs)}
      {summary.attempts.length > 1 && `, ${summary.attempts.length} attempts`}
      {summary.rowsIn !== null && <><br />{count(summary.rowsIn)} in → {count(summary.rowsOut)} out</>}
      {summary.rowsQuarantined ? <><br />{count(summary.rowsQuarantined)} quarantined</> : null}
    </span>}
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </div>
}
