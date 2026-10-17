import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { PipelineGraph } from '../../data/generated/pipeline_graph'
import type { RunLog } from '../../data/generated/run_log'
import { REPLAY_MS, edgeActive, nodeStages, replayEvents, stateAt, summarize } from './timeline'

const FIXTURES = resolve(import.meta.dirname, '../../../../fixtures/exports')
const runLog = JSON.parse(readFileSync(resolve(FIXTURES, 'run_log.json'), 'utf8')) as RunLog
const graph = JSON.parse(readFileSync(resolve(FIXTURES, 'pipeline_graph.json'), 'utf8')) as PipelineGraph
const retried = runLog.runs.find((r) => r.run_id === 'weekly-2026-W39-1')!

describe('summarize', () => {
  it('folds a retried stage into one summary that ends in its last attempt', () => {
    const ingest = summarize(retried).get('ingest')!
    expect(ingest.attempts.map((a) => a.status)).toEqual(['FAILED', 'SUCCESS'])
    expect(ingest.status).toBe('SUCCESS')
    expect(ingest.durationMs).toBe(ingest.attempts.reduce((s, a) => s + (a.duration_ms ?? 0), 0))
    expect(summarize(retried).get('dbt_build')!.status).toBe('WARN')
  })
})

describe('replay', () => {
  const events = replayEvents(retried)

  it('fits the run into the replay window, in time order', () => {
    expect(events[0]!.at).toBe(0)
    expect(Math.max(...events.map((e) => e.at))).toBeLessThanOrEqual(REPLAY_MS)
    expect(events.every((e, i) => i === 0 || events[i - 1]!.at <= e.at)).toBe(true)
  })

  it('shows the failed attempt, then the retry running, then the final state', () => {
    const ingest = events.filter((e) => e.stage === 'ingest')
    expect(ingest.map((e) => e.state)).toEqual(['RUNNING', 'FAILED', 'RUNNING', 'SUCCESS'])
    expect(stateAt(events, ingest[1]!.at).get('ingest')).toBe('FAILED')
    expect(stateAt(events, ingest[2]!.at).get('ingest')).toBe('RUNNING')
    const final = stateAt(events, Infinity)
    for (const [stage, summary] of summarize(retried)) expect(final.get(stage)).toBe(summary.status)
    expect(stateAt(events, -1).size).toBe(0)
  })

  it('runs particles only on edges into the running stage or the outputs it writes', () => {
    const stages = nodeStages(graph.nodes, graph.edges)
    expect(stages.get('dbt_marts')).toBe('dbt_build')
    expect(stages.get('src_snowflake')).toBe('generate')
    const state = new Map([['generate', 'RUNNING' as const]])
    const active = graph.edges.filter((e) => edgeActive(e, stages, state)).map((e) => e.id).sort()
    expect(active).toEqual(['generate->src_snowflake', 'generate->src_teradata', 'restore_state->generate'])
  })
})
