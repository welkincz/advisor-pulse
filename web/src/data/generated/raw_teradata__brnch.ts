/* Generated from contracts/schemas/raw.teradata__brnch.schema.json. Do not edit. */

export type BrnchId = string;
export type BrnchNm = string;
export type CloseDt = string | null;
export type DistCd = string;
export type FsaCd = string;
/**
 * Watermark column.
 */
export type LastUpdTs = string;
export type OpenDt = string;
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
 * Raw branch master.
 */
export interface RawTeradata_Brnch {
  BRNCH_ID: BrnchId;
  BRNCH_NM: BrnchNm;
  CLOSE_DT?: CloseDt;
  DIST_CD: DistCd;
  FSA_CD: FsaCd;
  LAST_UPD_TS: LastUpdTs;
  OPEN_DT: OpenDt;
  _batch_id: BatchId;
  _loaded_at: LoadedAt;
  _row_hash: RowHash;
  _source_file: SourceFile;
  _source_row: SourceRow;
}
