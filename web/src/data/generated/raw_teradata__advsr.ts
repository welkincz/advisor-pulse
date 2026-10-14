/* Generated from contracts/schemas/raw.teradata__advsr.schema.json. Do not edit. */

export type AdvsrId = string;
/**
 * Synthetic name.
 */
export type AdvsrNm = string;
export type HireDt = string;
/**
 * Watermark column.
 */
export type LastUpdTs = string;
export type Role = "ASSOC" | "ADVSR" | "SNR_ADVSR" | "BR_MGR";
export type TermDt = string | null;
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
 * Raw advisor master.
 */
export interface RawTeradata_Advsr {
  ADVSR_ID: AdvsrId;
  ADVSR_NM: AdvsrNm;
  HIRE_DT: HireDt;
  LAST_UPD_TS: LastUpdTs;
  ROLE_CD: Role;
  TERM_DT?: TermDt;
  _batch_id: BatchId;
  _loaded_at: LoadedAt;
  _row_hash: RowHash;
  _source_file: SourceFile;
  _source_row: SourceRow;
}
