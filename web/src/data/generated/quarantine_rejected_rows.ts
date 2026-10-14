/* Generated from contracts/schemas/quarantine.rejected_rows.schema.json. Do not edit. */

export type BatchId = string;
export type DetectedAt = string;
/**
 * The rejected row as a JSON object string.
 */
export type Payload = string;
export type Reason = string;
export type RejectedId = string;
export type RuleId = string;
export type RunId = string;
export type Source = string;
export type SourceFile = string;
export type SourceRow = number;
export type TableName = string;

/**
 * Rows rejected at ingest, with the rule that rejected them.
 */
export interface QuarantineRejectedRows {
  batch_id: BatchId;
  detected_at: DetectedAt;
  payload: Payload;
  reason: Reason;
  rejected_id: RejectedId;
  rule_id: RuleId;
  run_id: RunId;
  source: Source;
  source_file: SourceFile;
  source_row: SourceRow;
  table_name: TableName;
}
