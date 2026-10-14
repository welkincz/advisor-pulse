/* Generated from contracts/schemas/pipeline_graph.schema.json. Do not edit. */

export type Id = string;
export type Source = string;
export type Target = string;
export type Edges = PipelineEdge[];
/**
 * @minItems 1
 */
export type Nodes = [PipelineNode, ...PipelineNode[]];
/**
 * Stable across runs.
 */
export type Id1 = string;
export type PipelineNodeKind = "SOURCE" | "STAGE" | "DBT_LAYER" | "OUTPUT";
export type Label = string;
/**
 * dbt models in a DBT_LAYER node.
 */
export type Models = string[];
export type X = number;
export type Y = number;
/**
 * Runner stage whose run_log rows map here.
 */
export type Stage = string | null;
export type SchemaVersion = string;

/**
 * data/pipeline_graph.json: nodes and edges for the React Flow view.
 */
export interface PipelineGraph {
  edges: Edges;
  nodes: Nodes;
  schema_version?: SchemaVersion;
}
export interface PipelineEdge {
  id: Id;
  source: Source;
  target: Target;
}
export interface PipelineNode {
  id: Id1;
  kind: PipelineNodeKind;
  label: Label;
  models?: Models;
  position: Position;
  stage?: Stage;
}
export interface Position {
  x: X;
  y: Y;
}
