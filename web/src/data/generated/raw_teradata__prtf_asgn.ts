/* Generated from contracts/schemas/raw.teradata__prtf_asgn.schema.json. Do not edit. */

export type AdvsrId = string;
export type EffDt = string;
/**
 * Watermark column.
 */
export type LastUpdTs = string;
export type PasgnId = string;
export type PrtfId = string;
/**
 * Why a portfolio changed hands (PRTF_ASGN.RSN_CD, PLAN.md §6.2).
 */
export type PortfolioAssignmentReason = "OPEN" | "HANDOVER" | "TRANSFER" | "REBALANCE";
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
 * Raw portfolio assignment events.
 */
export interface RawTeradata_PrtfAsgn {
  ADVSR_ID: AdvsrId;
  EFF_DT: EffDt;
  LAST_UPD_TS: LastUpdTs;
  PASGN_ID: PasgnId;
  PRTF_ID: PrtfId;
  RSN_CD: PortfolioAssignmentReason;
  _batch_id: BatchId;
  _loaded_at: LoadedAt;
  _row_hash: RowHash;
  _source_file: SourceFile;
  _source_row: SourceRow;
}
