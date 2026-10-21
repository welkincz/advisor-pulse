import { describe, expect, it } from 'vitest'
import type { PipelineNode } from '../../data/generated/pipeline_graph'
import { labelLines } from './PipelineDiagram'
import { runShare } from './StageTimeline'
import { stageCard } from './explain'
import type { StageSummary } from './timeline'

const node = (over: Partial<PipelineNode>): PipelineNode => ({ id: 'ingest', kind: 'STAGE', stage: 'ingest', label: 'Ingest + validate', position: { x: 0, y: 0 }, ...over }) as PipelineNode
const summary = (over: Partial<StageSummary>): StageSummary => ({ stage: 'ingest', status: 'SUCCESS', attempts: [{ attempt: 1, status: 'SUCCESS' }] as StageSummary['attempts'], durationMs: 40_100, rowsIn: 15_115, rowsOut: 15_010, rowsQuarantined: 105, ...over })

describe('stageCard', () => {
  it('says what the stage does and what happened, rows included', () => {
    const card = stageCard(node({}), summary({}), false)
    expect(card.what).toMatch(/quarantines rows/)
    expect(card.happened).toEqual(['Succeeded in 40.1 s.', '15,115 rows in, 15,010 out, 105 quarantined.'])
    expect(card.answer).toBeUndefined()
  })

  it('answers why a stage warned, from its message, and why a logged-mid-run stage is running', () => {
    const warned = summary({ status: 'WARN', attempts: [{ attempt: 1, status: 'WARN', message: 'DQ031 WARN' }] as StageSummary['attempts'] })
    expect(stageCard(node({}), warned, false).answer).toEqual({ q: 'Why a warning?', a: 'DQ031 WARN' })
    expect(stageCard(node({}), summary({ status: 'RUNNING' }), true).answer?.q).toBe('Why is it still running?')
    expect(stageCard(node({ stage: 'export', label: 'Export' }), undefined, true).answer?.q).toBe('Why not run?')
  })

  it('names sources and outputs plainly', () => {
    expect(stageCard(node({ kind: 'OUTPUT', stage: undefined, label: 'pulse.charliebuild.com' }), undefined, false)).toEqual({ title: 'pulse.charliebuild.com', what: 'Where the weekly run publishes.' })
  })
})

describe('dbt layers and shares', () => {
  it('gives a dbt layer the build’s outcome as well as its models', () => {
    const layer = node({ id: 'dbt_marts', kind: 'DBT_LAYER', stage: 'dbt_build', label: 'Marts (13 models)', models: ['mart_a', 'mart_b'] } as Partial<PipelineNode>)
    const card = stageCard(layer, summary({ status: 'WARN', attempts: [{ attempt: 1, status: 'WARN', message: '1 warned' }] as StageSummary['attempts'] }), false)
    expect(card.title).toBe('Marts (13 models)')
    expect(card.happened).toContain('2 models: mart_a, mart_b')
    expect(card.answer?.a).toBe('1 warned')
  })

  it('says 0% for no time and <1% for a sliver', () => {
    expect(runShare(0, 1000)).toBe('0%')
    expect(runShare(5, 1000)).toBe('<1%')
    expect(runShare(250, 1000)).toBe('25%')
  })
})

describe('labelLines', () => {
  it('draws an output’s web address as "Website", so it does not run into its neighbour', () => {
    expect(labelLines('pulse.charliebuild.com', 13, true)).toEqual(['Website'])
    expect(labelLines('v1.2.3')).toEqual(['v1.2.3'])
    expect(labelLines('Marts (13 models)')).toEqual(['Marts', '13 models'])
  })
})
