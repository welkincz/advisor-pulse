import { BaseEdge, type Edge, type EdgeProps, getBezierPath } from '@xyflow/react'

export type FlowEdgeData = { active: boolean }
export type PipelineFlowEdge = Edge<FlowEdgeData, 'flow'>

/** A plain edge; while data flows along it, two particles travel source to target (SVG, off the main thread). */
export function FlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps<PipelineFlowEdge>) {
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  const active = data?.active ?? false
  return <>
    <BaseEdge id={id} path={path} className={active ? 'pipe-edge is-active' : 'pipe-edge'} />
    {active && [0, 0.45].map((begin) => <circle key={begin} r="4" className="pipe-particle">
      <animateMotion dur="0.9s" begin={`${begin}s`} repeatCount="indefinite" path={path} />
    </circle>)}
  </>
}
