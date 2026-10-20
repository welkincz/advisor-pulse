import type { KeyboardEvent } from 'react'
import type { PipelineGraph, PipelineNode } from '../../data/generated/pipeline_graph'
import { formatDuration } from './format'
import { type NodeState, type StageSummary, edgeActive, nodeStages } from './timeline'

const COLUMN = 240
const LANE = 80
const MIN_COL_W = 78
const LANE_H = 50
const PAD_X = 40
const PAD_TOP = 26
const LABEL_SPACE = 44

const WORD: Record<string, string> = { SUCCESS: 'Succeeded', WARN: 'Warning', FAILED: 'Failed', SKIPPED: 'Skipped', RUNNING: 'Running', PENDING: 'Waiting' }
const GLYPH: Record<string, string> = { SUCCESS: '✓', WARN: '!', FAILED: '✕', SKIPPED: '–' }

/** A label in at most two short lines: "Marts (12 models)" becomes "Marts" over "12 models". */
export function labelLines(label: string, width = 13): string[] {
  const bracket = /^(.*?)\s*\((.+)\)$/.exec(label)
  if (bracket) return [bracket[1]!, bracket[2]!]
  if (label.length <= width || !label.includes(' ')) return [label]
  const words = label.split(' ')
  let first = words.shift()!
  while (words.length && `${first} ${words[0]}`.length <= width) first += ` ${words.shift()}`
  return words.length ? [first, words.join(' ')] : [first]
}

/** Grid positions from the export's layout: columns of 240 and lanes of 80 graph units. */
export function gridOf(nodes: readonly PipelineNode[]) {
  const cols = nodes.map((n) => Math.round(n.position.x / COLUMN))
  const lanes = nodes.map((n) => Math.round(n.position.y / LANE))
  const minCol = Math.min(...cols)
  const minLane = Math.min(...lanes)
  return {
    cells: new Map(nodes.map((n, i) => [n.id, { col: cols[i]! - minCol, lane: lanes[i]! - minLane }])),
    columns: Math.max(...cols) - minCol + 1,
    lanes: Math.max(...lanes) - minLane + 1,
  }
}

/**
 * The weekly DAG as a line diagram: stations for stages, small stops for the dbt layers,
 * open squares for sources and outputs. During a replay the line in use carries a moving
 * dash and each station fills with its outcome. Stations are buttons: Enter opens details.
 */
export function PipelineDiagram({ graph, state, summaries, selected, onSelect, width, replaying }: {
  graph: PipelineGraph
  state: ReadonlyMap<string, NodeState>
  summaries: ReadonlyMap<string, StageSummary>
  selected: string | null
  onSelect: (id: string) => void
  width: number
  replaying: boolean
}) {
  const { cells, columns, lanes } = gridOf(graph.nodes)
  const colW = Math.max(MIN_COL_W, (width - 2 * PAD_X) / Math.max(1, columns - 1))
  const svgW = PAD_X * 2 + colW * (columns - 1)
  const svgH = PAD_TOP + (lanes - 1) * LANE_H + LABEL_SPACE + 8
  const at = (id: string) => {
    const cell = cells.get(id)!
    return { x: PAD_X + cell.col * colW, y: PAD_TOP + cell.lane * LANE_H }
  }
  const stages = nodeStages(graph.nodes, graph.edges)
  const stateOf = (node: PipelineNode): NodeState | null => (node.stage ? state.get(node.stage) ?? 'PENDING' : null)
  const done = (s: NodeState | null | undefined) => s != null && s !== 'PENDING' && s !== 'RUNNING'

  const onKey = (event: KeyboardEvent<SVGGElement>, id: string) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    onSelect(id)
  }

  return <svg className={`line-diagram${replaying ? ' is-replaying' : ''}`} width={svgW} height={svgH} viewBox={`0 0 ${svgW} ${svgH}`}>
    <g className="line-edges" aria-hidden="true">
      {graph.edges.map((edge) => {
        const a = at(edge.source)
        const b = at(edge.target)
        const mid = (a.x + b.x) / 2
        const d = a.y === b.y ? `M${a.x},${a.y}L${b.x},${b.y}` : `M${a.x},${a.y}C${mid},${a.y} ${mid},${b.y} ${b.x},${b.y}`
        const active = edgeActive(edge, stages, state)
        const target = stages.get(edge.target)
        const travelled = done(target ? state.get(target) : null)
        return <path key={edge.id} d={d} className={`line-edge${active ? ' is-active' : travelled ? ' is-done' : ''}`} />
      })}
    </g>
    {graph.nodes.map((node) => {
      const { x, y } = at(node.id)
      const s = stateOf(node)
      const summary = node.stage ? summaries.get(node.stage) : undefined
      const word = s ? WORD[s] : node.kind === 'SOURCE' ? 'Source' : 'Output'
      const detail = node.kind === 'STAGE' && summary && done(s) ? formatDuration(summary.durationMs) : ''
      const label = `${node.label}, ${word}${detail ? `, ${detail}` : ''}`
      const small = node.kind === 'DBT_LAYER'
      return <g key={node.id} className={`line-node line-node-${node.kind.toLowerCase()}${node.id === selected ? ' is-selected' : ''}`} data-node={node.id} data-state={s ?? 'NONE'}
        transform={`translate(${x} ${y})`} role="button" tabIndex={0} aria-label={label} aria-pressed={node.id === selected}
        onClick={() => onSelect(node.id)} onKeyDown={(event) => onKey(event, node.id)}>
        <circle className="line-hit" r={22} />
        {node.kind === 'SOURCE' || node.kind === 'OUTPUT'
          ? <rect className="line-mark" x={-8} y={-8} width={16} height={16} rx={3} />
          : <>
            {s === 'RUNNING' && <circle className="line-running" r={small ? 11 : 15} />}
            <circle className="line-mark" r={small ? 6 : 11} />
            {!small && s && GLYPH[s] && <text className="line-glyph" dy="0.35em" textAnchor="middle">{GLYPH[s]}</text>}
          </>}
        {(() => {
          // dbt layers sit close together on the main line, so their names go above it.
          const lines = labelLines(node.label)
          const top = small ? -14 - (lines.length - 1) * 13 : 28
          return <text className="line-label" y={top} textAnchor="middle">
            {lines.map((line, i) => <tspan key={i} x={0} dy={i ? 13 : 0} className={i ? 'line-label-more' : undefined}>{line}</tspan>)}
          </text>
        })()}
        {node.kind === 'STAGE' && <text className="line-sub" y={42 + (labelLines(node.label).length - 1) * 13} textAnchor="middle">{s === 'PENDING' ? 'Waiting' : s === 'RUNNING' ? 'Running' : detail || word}</text>}
      </g>
    })}
  </svg>
}
