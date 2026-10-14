/* Generated from contracts/schemas/teradata__advsr_asgn.schema.json. Do not edit. */

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
 * Advisor assignment events (ADVSR_ASGN) in sources/teradata/edw.sqlite; the input to SCD2 advisor history.
 */
export interface Teradata_AdvsrAsgn {
  ADVSR_ID: AdvsrId;
  ASGN_ID: AsgnId;
  BRNCH_ID: BrnchId;
  EFF_DT: EffDt;
  LAST_UPD_TS: LastUpdTs;
  ROLE_CD: Role;
  RSN_CD: AssignmentReason;
}
