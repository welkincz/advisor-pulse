/* Generated from contracts/schemas/teradata__prtf.schema.json. Do not edit. */

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
 * Portfolio master (PRTF) in sources/teradata/edw.sqlite: a group of clients managed by one advisor at a time, belonging to one branch (its transit).
 */
export interface Teradata_Prtf {
  BRNCH_ID: BrnchId;
  CLOSE_DT?: CloseDt;
  LAST_UPD_TS: LastUpdTs;
  OPEN_DT: OpenDt;
  PRTF_ID: PrtfId;
}
