import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useReducedMotion } from '../../app/useReducedMotion'
import { StatusMark } from '../../components/primitives'
import { DataNotice, usePipelineGraph, useRunLog } from '../../data'
import type { PipelineGraph, PipelineNode } from '../../data/generated/pipeline_graph'
import type { RunSummary } from '../../data/generated/run_log'
import { RunHistory } from './history/RunHistory'
import { formatDuration, runSentence, runTypeLabel } from './format'
import { PipelineDiagram } from './PipelineDiagram'
import { StageTimeline } from './StageTimeline'
import { replayEvents, summarize } from './timeline'
import { useReplay } from './useReplay'
import './pipeline.css'


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

function useWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    setWidth(element.clientWidth)
    const observer = new ResizeObserver(() => setWidth(element.clientWidth))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

function Canvas({ graph, run }: { graph: PipelineGraph; run: RunSummary }) {
  const reducedMotion = useReducedMotion()
  const events = useMemo(() => replayEvents(run), [run])
  const summaries = useMemo(() => summarize(run), [run])
  const { state, replaying, restart } = useReplay(events, reducedMotion)
  const [selected, setSelected] = useState<string | null>(null)
  const [box, width] = useWidth()
  useEffect(() => setSelected(null), [run])
  const node = graph.nodes.find((n) => n.id === selected)
  const date = runDate(run)
  const runType = runTypeLabel(run.run_type)
  const stageNodes = graph.nodes.filter((n) => n.kind === 'STAGE')
  const order = [...new Set(run.stages.map((s) => s.stage))]
  for (const n of stageNodes) if (!order.includes(n.stage!)) order.push(n.stage!)
  const labels = new Map(stageNodes.map((n) => [n.stage!, n.label]))

  return <>
    <div className="pipe-bar">
      <p className="pipe-replay" aria-live="polite">{replaying ? `Replaying ${runType.toLowerCase()} run of ${date}` : `${runType} run of ${date}`}: <StatusMark status={run.status} /></p>
      <button type="button" onClick={restart} disabled={reducedMotion || replaying}>Replay run</button>
      {reducedMotion && <span className="pipe-note">Replay is off because your system asks for reduced motion.</span>}
    </div>
    {run.stages.some((s) => s.status === 'RUNNING') && <p className="pipe-note pipe-inflight">This run wrote its log during the export stage, so export shows as running and the stages after it as waiting. The next run's log records how they finished.</p>}
    <div className="pipe-layout">
      <div className="pipe-canvas" ref={box} role="group" aria-label="Pipeline stages">
        {width > 0 && <PipelineDiagram graph={graph} state={state} summaries={summaries} selected={selected} onSelect={setSelected} width={width} replaying={replaying} />}
      </div>
      {node && <DetailPanel node={node} run={run} onClose={() => setSelected(null)} />}
    </div>
    <section className="pipe-time" aria-labelledby="pipe-time-title">
      <h2 id="pipe-time-title">Where the time went</h2>
      <StageTimeline order={order} labels={labels} summaries={summaries} state={state}
        onSelect={(stage) => setSelected(graph.nodes.find((n) => n.stage === stage && n.kind === 'STAGE')?.id ?? null)} />
    </section>
    <details className="pipe-list">
      <summary>Stages as a table</summary>
      <table className="pipe-table">
        <thead><tr><th scope="col">Stage</th><th scope="col">Status</th><th scope="col" className="num">Duration</th><th scope="col" className="num">Attempts</th></tr></thead>
        <tbody>{stageNodes.map((n) => {
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
  const latestWeekly = runs.find((r) => r.run_type === 'WEEKLY')

  return <main className="pipe-page">
    <p className="eyebrow">Maplecrest Bank · fictional</p>
    <h1>Pipeline</h1>
    <p className="intro">{latestWeekly ? runSentence(latestWeekly) : 'The weekly batch from source extracts to the published report.'} Choose a stage for its attempts, rows and checks.</p>
    {(graph.status === 'loading' || runLog.status === 'loading') && <p aria-busy="true">Loading the pipeline…</p>}
    {graph.status === 'error' && <DataNotice what="the pipeline graph" onRetry={graph.retry} />}
    {runLog.status === 'error' && <DataNotice what="the run log" onRetry={runLog.retry} />}
    {runLog.status === 'empty' && <p>No weekly run has been recorded yet.</p>}
    {runs.length > 1 && run && <RunHistory runs={runs} selectedId={run.run_id} onSelect={setRunId} />}
    {graph.status === 'ready' && run && <Canvas graph={graph.data} run={run} />}
  </main>
}
