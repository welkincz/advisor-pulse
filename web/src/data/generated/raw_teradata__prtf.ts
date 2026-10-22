/* Generated from contracts/schemas/raw.teradata__prtf.schema.json. Do not edit. */

/**
 * Transit: the owning branch.
 */
export type BrnchId = string;
export type CloseDt = string | null;
/**
 * Watermark column.
 */
export type LastUpdTs = string;
export type OpenDt = string;
export type PrtfId = string;
/**
 * run_id + source + file hash prefix.
 */
export type BatchId = string;
export type LoadedAt = string;
/**
 * xxhash of business columns.
 */
export type RowHash = string;
/**
 * Relative path.
 */
export type SourceFile = string;
/**
 * Row number in the file.
 */
export type SourceRow = number;

/**
 * Raw portfolio master.
 */
export interface RawTeradata_Prtf {
  BRNCH_ID: BrnchId;
  CLOSE_DT?: CloseDt;
  LAST_UPD_TS: LastUpdTs;
  OPEN_DT: OpenDt;
  PRTF_ID: PrtfId;
  _batch_id: BatchId;
  _loaded_at: LoadedAt;
  _row_hash: RowHash;
  _source_file: SourceFile;
  _source_row: SourceRow;
}
