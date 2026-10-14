/* Generated from contracts/schemas/raw.teradata__advsr_asgn.schema.json. Do not edit. */

export type AdvsrId = string;
export type AsgnId = string;
export type BrnchId = string;
export type EffDt = string;
/**
 * Watermark column.
 */
export type LastUpdTs = string;
export type Role = "ASSOC" | "ADVSR" | "SNR_ADVSR" | "BR_MGR";
export type AssignmentReason = "HIRE" | "TRANSFER" | "PROMOTION" | "TERM";
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
 * Raw advisor assignment events.
 */
export interface RawTeradata_AdvsrAsgn {
  ADVSR_ID: AdvsrId;
  ASGN_ID: AsgnId;
  BRNCH_ID: BrnchId;
  EFF_DT: EffDt;
  LAST_UPD_TS: LastUpdTs;
  ROLE_CD: Role;
  RSN_CD: AssignmentReason;
  _batch_id: BatchId;
  _loaded_at: LoadedAt;
  _row_hash: RowHash;
  _source_file: SourceFile;
  _source_row: SourceRow;
}
