/* Generated from contracts/schemas/teradata__brnch.schema.json. Do not edit. */

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
 * Branch master (BRNCH) in sources/teradata/edw.sqlite.
 */
export interface Teradata_Brnch {
  BRNCH_ID: BrnchId;
  BRNCH_NM: BrnchNm;
  CLOSE_DT?: CloseDt;
  DIST_CD: DistCd;
  FSA_CD: FsaCd;
  LAST_UPD_TS: LastUpdTs;
  OPEN_DT: OpenDt;
}
