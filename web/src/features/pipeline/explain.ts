import type { CardContent } from '../../components/primitives'
import type { PipelineNode } from '../../data/generated/pipeline_graph'
import { formatDuration } from './format'
import type { StageSummary } from './timeline'

/** What each stage does, in a sentence a reader new to data pipelines can follow. */
export const STAGE_PLAIN: Record<string, string> = {
  restore_state: 'Takes the run lock and loads last week’s warehouse, so the run picks up where the last one stopped.',
  generate: 'Writes this week’s synthetic extracts: activity, clients and advisors, with known defects mixed in.',
  ingest: 'Loads the new extracts, skips files it has seen, and quarantines rows that fail validation.',
  dbt_build: 'Builds and tests the models: staging cleans the sources, intermediate joins them, marts are what the site reads.',
  checks: 'Runs the data-quality rules, so a bad week is flagged before it is published.',
  narrate: 'Writes each region’s summary from the week’s figures, then checks every number against them.',
  export: 'Writes the marts to the files this site reads.',
  publish_sheets: 'Copies the report to Google Sheets.',
  persist_state: 'Saves the warehouse and new extracts, so next week’s run starts from here.',
  release_lock: 'Releases the run lock, so the next run can start.',
}

const WORD: Record<string, string> = { SUCCESS: 'Succeeded', WARN: 'Warning', FAILED: 'Failed', SKIPPED: 'Skipped', RUNNING: 'Running' }
const count = (n: number | null) => (n == null ? null : n.toLocaleString('en-CA'))

/**
 * The card for a node of the diagram: what it is, what happened to it in this run, and the
 * question the diagram raises about it. `inflight` is true when the run's log was written
 * before the run finished, so later stages read as running or waiting.
 */
export function stageCard(node: PipelineNode, summary: StageSummary | undefined, inflight: boolean): CardContent {
  if (node.kind === 'SOURCE') return { title: node.label, what: 'A source the weekly run reads.' }
  if (node.kind === 'OUTPUT') return { title: node.label, what: 'Where the weekly run publishes.' }
  const what = STAGE_PLAIN[node.stage ?? ''] ?? undefined
  if (node.kind === 'DBT_LAYER') {
    // A layer is part of the dbt build: its card carries the build's outcome, then the layer's models.
    const build = stageCard({ ...node, kind: 'STAGE', label: 'dbt build' }, summary, inflight)
    const models = node.models?.length ? [`${node.models.length} models: ${node.models.slice(0, 4).join(', ')}${node.models.length > 4 ? ', …' : ''}`] : []
    return { ...build, title: node.label, happened: [...(build.happened ?? []), ...models], hint: 'Click for every model.' }
  }
  if (!summary) {
    return {
      title: node.label, what, value: 'Not run',
      answer: inflight ? { q: 'Why not run?', a: 'This log was written while the run was still going, before this stage. The next run’s log records how it finished.' } : undefined,
    }
  }
  const happened: string[] = []
  const attempts = summary.attempts.length
  if (summary.status !== 'RUNNING') happened.push(`${WORD[summary.status] ?? summary.status} in ${formatDuration(summary.durationMs)}${attempts > 1 ? `, after ${attempts} attempts` : ''}.`)
  const rows = [count(summary.rowsIn) && `${count(summary.rowsIn)} rows in`, count(summary.rowsOut) && `${count(summary.rowsOut)} out`, summary.rowsQuarantined ? `${count(summary.rowsQuarantined)} quarantined` : null].filter(Boolean)
  if (rows.length) happened.push(`${rows.join(', ')}.`)
  const message = summary.attempts.at(-1)?.message ?? null
  const answer = summary.status === 'RUNNING'
    ? { q: 'Why is it still running?', a: 'This log was written while the stage was going. The next run’s log records how it finished.' }
    : (summary.status === 'WARN' || summary.status === 'FAILED') && message
      ? { q: summary.status === 'WARN' ? 'Why a warning?' : 'Why did it fail?', a: message }
      : undefined
  return { title: node.label, value: summary.status === 'RUNNING' ? 'Running' : formatDuration(summary.durationMs), what, happened, answer, hint: 'Click for attempts, rows and checks.' }
}
