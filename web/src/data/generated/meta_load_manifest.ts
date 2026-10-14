/* Generated from contracts/schemas/meta.load_manifest.schema.json. Do not edit. */

export type BatchId = string;
export type FilePath = string;
export type FileSha256 = string;
export type LoadedAt = string;
export type RowCount = number;
export type RowsLoaded = number;
export type RowsQuarantined = number;
export type RunId = string;
export type Source = string;
export type LoadStatus = "LOADED" | "SKIPPED_DUPLICATE" | "FAILED";
export type TableName = string;

/**
 * One row per file seen. Primary key: (file_path, file_sha256); a changed file is a new row.
 */
export interface MetaLoadManifest {
  batch_id: BatchId;
  file_path: FilePath;
  file_sha256: FileSha256;
  loaded_at: LoadedAt;
  row_count: RowCount;
  rows_loaded: RowsLoaded;
  rows_quarantined: RowsQuarantined;
  run_id: RunId;
  source: Source;
  status: LoadStatus;
  table_name: TableName;
}
