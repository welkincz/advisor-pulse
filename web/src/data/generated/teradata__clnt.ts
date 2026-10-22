/* Generated from contracts/schemas/teradata__clnt.schema.json. Do not edit. */

export type BrthYr = number;
export type ClntId = string;
/**
 * Relationship start.
 */
export type ClntSinceDt = string;
/**
 * Watermark column.
 */
export type LastUpdTs = string;
export type PrimBrnchId = string;
/**
 * Provinces in scope. Territories are out of scope for the fictional network.
 */
export type Province = "ON" | "QC" | "BC" | "AB" | "SK" | "MB" | "NS" | "PE" | "NB" | "NL";
/**
 * Portfolio the client belongs to; its holder at week end owns the book.
 */
export type PrtfId = string;
/**
 * Raw postal code; normalized in staging.
 */
export type PstlCd = string | null;
export type Segment = "MASS" | "MAFF" | "AFFL" | "SMBS";
export type ClientStatus = "A" | "C";

/**
 * Client master (CLNT) in sources/teradata/edw.sqlite; daily deltas in client_YYYYMMDD.csv share these columns.
 */
export interface Teradata_Clnt {
  BRTH_YR: BrthYr;
  CLNT_ID: ClntId;
  CLNT_SINCE_DT: ClntSinceDt;
  LAST_UPD_TS: LastUpdTs;
  PRIM_BRNCH_ID: PrimBrnchId;
  PROV_CD: Province;
  PRTF_ID: PrtfId;
  PSTL_CD?: PstlCd;
  SEG_CD: Segment;
  STAT_CD: ClientStatus;
}
