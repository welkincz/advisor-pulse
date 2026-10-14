/* Generated from contracts/schemas/teradata__advsr.schema.json. Do not edit. */

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
 * Advisor master (ADVSR) in sources/teradata/edw.sqlite.
 */
export interface Teradata_Advsr {
  ADVSR_ID: AdvsrId;
  ADVSR_NM: AdvsrNm;
  HIRE_DT: HireDt;
  LAST_UPD_TS: LastUpdTs;
  ROLE_CD: Role;
  TERM_DT?: TermDt;
}
