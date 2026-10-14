/* Generated from contracts/schemas/meta.watermark.schema.json. Do not edit. */

export type RunId = string;
export type Source = string;
export type TableName = string;
export type UpdatedAt = string;
export type WatermarkColumn = string;
export type WatermarkValue = string;

/**
 * High-water mark per (source, table_name). Primary key: both columns.
 */
export interface MetaWatermark {
  run_id: RunId;
  source: Source;
  table_name: TableName;
  updated_at: UpdatedAt;
  watermark_column: WatermarkColumn;
  watermark_value: WatermarkValue;
}
