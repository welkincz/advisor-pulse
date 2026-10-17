import { Background, Controls, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/base.css'
import { useEffect, useMemo, useState } from 'react'
import { useReducedMotion } from '../../app/useReducedMotion'
import { StatusMark } from '../../components/primitives'
import { DataNotice, usePipelineGraph, useRunLog } from '../../data'
import type { PipelineGraph, PipelineNode } from '../../data/generated/pipeline_graph'
import type { RunSummary } from '../../data/generated/run_log'
import { FlowEdge, type PipelineFlowEdge } from './FlowEdge'
import { RunHistory, runTypeLabel } from './history/RunHistory'
import { StageNode, type StageFlowNode, formatDuration } from './StageNode'
import { type NodeState, edgeActive, nodeStages, replayEvents, summarize } from './timeline'
import { useReplay } from './useReplay'
import './pipeline.css'

const nodeTypes = { stage: StageNode }
const edgeTypes = { flow: FlowEdge }
const ZOOM = 0.8
const CANVAS_PAD = 24

export function runDate(run: RunSummary): string {
  return new Date(run.started_at).toLocaleDateString('en-CA', { timeZone: 'America/Toronto', day: 'numeric', month: 'long', year: 'numeric' })
}

function DetailPanel({ node, run, onClose }: { node: PipelineNode; run: RunSummary; onClose: () => void }) {
  const summary = node.stage ? summarize(run).get(node.stage) : undefined
  useEffect(() => {
    const close = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [onClose])
  return <aside className="pipe-panel" aria-labelledby="pipe-panel-title">
    <div className="pipe-panel-head">
      <h3 id="pipe-panel-title">{node.label}</h3>
      <button type="button" onClick={onClose}>Close</button>
    </div>
    {summary && <p><StatusMark status={summary.status} /> in {formatDuration(summary.durationMs)}{summary.attempts.length > 1 && `, after ${summary.attempts.length} attempts`}.</p>}
    {!node.stage && <p>{node.kind === 'SOURCE' ? 'A source the weekly run reads.' : 'Where the weekly run publishes.'}</p>}
    {node.models && node.models.length > 0 && <>
      <h4>Models ({node.models.length})</h4>
      <ul className="pipe-models">{node.models.map((m) => <li key={m}>{m}</li>)}</ul>
    </>}
    {summary && <>
      <h4>Attempts</h4>
      <table className="pipe-table">
        <thead><tr><th scope="col">#</th><th scope="col">Status</th><th scope="col" className="num">Duration</th><th scope="col" className="num">Rows in</th><th scope="col" className="num">Rows out</th><th scope="col" className="num">Quarantined</th></tr></thead>
        <tbody>{summary.attempts.map((a) => <tr key={a.attempt}>
          <th scope="row">{a.attempt}</th><td><StatusMark status={a.status} /></td>
          <td className="num">{formatDuration(a.duration_ms ?? 0)}</td>
          <td className="num">{a.rows_in?.toLocaleString('en-CA') ?? '–'}</td>
          <td className="num">{a.rows_out?.toLocaleString('en-CA') ?? '–'}</td>
          <td className="num">{a.rows_quarantined?.toLocaleString('en-CA') ?? '–'}</td>
        </tr>)}</tbody>
      </table>
      <ul className="pipe-messages">{summary.attempts.filter((a) => a.message).map((a) => <li key={a.attempt}>Attempt {a.attempt}: {a.message}</li>)}</ul>
    </>}
    {node.stage === 'checks' && <>
      <h4>Check results</h4>
      {run.checks.length === 0 ? <p>No checks were recorded for this run.</p> : <table className="pipe-table">
        <thead><tr><th scope="col">Check</th><th scope="col">Status</th><th scope="col">Detail</th></tr></thead>
        <tbody>{run.checks.map((c) => <tr key={c.check_id}>
          <th scope="row">{c.check_id}</th>
          <td><StatusMark status={c.status === 'PASS' ? 'SUCCESS' : c.status === 'WARN' ? 'WARN' : 'FAILED'} label={`${c.status} (${c.severity.toLowerCase()})`} /></td>
          <td>{c.message ?? `${c.observed ?? ''}${c.expected ? ` vs ${c.expected}` : ''}`}</td>
        </tr>)}</tbody>
      </table>}
    </>}
  </aside>
}

function Canvas({ graph, run }: { graph: PipelineGraph; run: RunSummary }) {
  const reducedMotion = useReducedMotion()
  const events = useMemo(() => replayEvents(run), [run])
  const summaries = useMemo(() => summarize(run), [run])
  const stages = useMemo(() => nodeStages(graph.nodes, graph.edges), [graph])
  const { state, replaying, restart } = useReplay(events, reducedMotion)
  const [selected, setSelected] = useState<string | null>(null)
  useEffect(() => setSelected(null), [run])

  const stateOf = (node: PipelineNode): NodeState | null =>
    node.kind === 'STAGE' || node.kind === 'DBT_LAYER' ? state.get(node.stage!) ?? 'PENDING' : null
  const nodes: StageFlowNode[] = graph.nodes.map((node) => ({
    id: node.id,
    type: 'stage',
    position: node.position,
    selected: node.id === selected,
    data: { label: node.label, kind: node.kind, state: stateOf(node), summary: node.stage ? summaries.get(node.stage) ?? null : null },
  }))
  const edges: PipelineFlowEdge[] = graph.edges.map((edge) => ({
    id: edge.id, source: edge.source, target: edge.target, type: 'flow',
    data: { active: edgeActive(edge, stages, state) },
  }))
  // Readable rather than fitted: the DAG is far wider than tall, so it starts at the left
  // edge at a fixed zoom and pans sideways (drag, or the controls).
  const viewport = useMemo(() => {
    const minX = Math.min(...graph.nodes.map((n) => n.position.x))
    const minY = Math.min(...graph.nodes.map((n) => n.position.y))
    return { x: CANVAS_PAD - minX * ZOOM, y: CANVAS_PAD - minY * ZOOM, zoom: ZOOM }
  }, [graph])
  const node = graph.nodes.find((n) => n.id === selected)
  const date = runDate(run)
  const runType = runTypeLabel(run.run_type)

  return <>
    <div className="pipe-bar">
      <p className="pipe-replay" aria-live="polite">{replaying ? `Replaying ${runType.toLowerCase()} run of ${date}` : `${runType} run of ${date}`}: <StatusMark status={run.status} /></p>
      <button type="button" onClick={restart} disabled={reducedMotion || replaying}>Replay run</button>
      {reducedMotion && <span className="pipe-note">Replay is off because your system asks for reduced motion.</span>}
    </div>
    <div className="pipe-layout">
      <div className="pipe-canvas">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} defaultViewport={viewport} minZoom={0.2} maxZoom={1.5}
          zoomOnScroll={false} preventScrolling={false}
          nodesDraggable={false} nodesConnectable={false} edgesFocusable={false} proOptions={{ hideAttribution: true }}
          onNodeClick={(_, n) => setSelected(n.id)} onPaneClick={() => setSelected(null)}
          onKeyDown={(event) => {
            const id = (event.target as HTMLElement).closest('[data-id]')?.getAttribute('data-id')
            if (event.key === 'Enter' && id) setSelected(id)
          }}>
          <Background gap={24} size={1} />
          <Controls position="bottom-right" showInteractive={false} />
        </ReactFlow>
      </div>
      {node && <DetailPanel node={node} run={run} onClose={() => setSelected(null)} />}
    </div>
    <details className="pipe-list">
      <summary>Stages as a table</summary>
      <table className="pipe-table">
        <thead><tr><th scope="col">Stage</th><th scope="col">Status</th><th scope="col" className="num">Duration</th><th scope="col" className="num">Attempts</th></tr></thead>
        <tbody>{graph.nodes.filter((n) => n.kind === 'STAGE').map((n) => {
          const s = summaries.get(n.stage!)
          return <tr key={n.id}>
            <th scope="row"><button type="button" className="pipe-link" onClick={() => setSelected(n.id)}>{n.label}</button></th>
            <td>{s ? <StatusMark status={s.status} /> : 'Not run'}</td>
            <td className="num">{s ? formatDuration(s.durationMs) : '–'}</td>
            <td className="num">{s?.attempts.length ?? 0}</td>
          </tr>
        })}</tbody>
      </table>
    </details>
  </>
}

/** The weekly DAG from pipeline_graph.json, replaying a run from run_log.json. */
export function PipelinePage() {
  const graph = usePipelineGraph()
  const runLog = useRunLog()
  const [runId, setRunId] = useState<string | null>(null)
  const runs = runLog.status === 'ready' ? runLog.data.runs : []
  const run = runs.find((r) => r.run_id === runId) ?? runs[0]

  return <main className="pipe-page">
    <p className="eyebrow">Maplecrest Bank · fictional</p>
    <h1>Pipeline</h1>
    <p className="intro">The weekly batch from source extracts to the published report. Select a step, or focus it and press Enter, for its attempts, rows and checks.</p>
    {(graph.status === 'loading' || runLog.status === 'loading') && <p aria-busy="true">Loading the pipeline…</p>}
    {graph.status === 'error' && <DataNotice what="the pipeline graph" onRetry={graph.retry} />}
    {runLog.status === 'error' && <DataNotice what="the run log" onRetry={runLog.retry} />}
    {runLog.status === 'empty' && <p>No weekly run has been recorded yet.</p>}
    {runs.length > 1 && run && <RunHistory runs={runs} selectedId={run.run_id} onSelect={setRunId} />}
    {graph.status === 'ready' && run && <Canvas graph={graph.data} run={run} />}
  </main>
}
