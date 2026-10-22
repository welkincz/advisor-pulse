/* Generated from contracts/schemas/teradata__prtf_asgn.schema.json. Do not edit. */

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
 * Portfolio assignment events (PRTF_ASGN) in sources/teradata/edw.sqlite: who holds each portfolio from EFF_DT on; the input to SCD2 portfolio history.
 */
export interface Teradata_PrtfAsgn {
  ADVSR_ID: AdvsrId;
  EFF_DT: EffDt;
  LAST_UPD_TS: LastUpdTs;
  PASGN_ID: PasgnId;
  PRTF_ID: PrtfId;
  RSN_CD: PortfolioAssignmentReason;
}
