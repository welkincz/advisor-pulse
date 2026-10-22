/* Generated from contracts/schemas/manifest.schema.json. Do not edit. */

export type Bytes = number;
/**
 * Path relative to the data/ directory.
 */
export type Name = string;
/**
 * Null for JSON documents.
 */
export type Rows = number | null;
export type Sha256 = string;
export type Files = ExportFile[];
export type GeneratedAt = string;
/**
 * True when geo/fsa.topo.json shipped (optional layer).
 */
export type HasFsaBoundaries = boolean;
export type LatestWeek = string;
export type RunId = string;
export type SchemaVersion = string;
export type ReportFlag = "UP" | "DOWN" | "FLAT" | "ANOMALY";
/**
 * KPI codes from PLAN.md §7.
 */
export type KpiCode =
  | "PRTF_CONTACT_12M"
  | "ACT_PER_ADV"
  | "CALLS_OUT"
  | "APPT_BOOKED"
  | "CALL_TO_APPT"
  | "SHOW_RATE"
  | "APPT_CONV"
  | "CLIENTS_CONTACTED"
  | "COVERAGE_13W"
  | "AVG_MEET_MIN"
  | "NO_SHOW_RATE"
  | "LATE_RATE"
  | "QUAR_RATE";
export type PriorWeekValue = number | null;
export type Value = number | null;
export type WowPct = number | null;
/**
 * National KPIs for latest_week.
 */
export type Summary = SummaryKpi[];
/**
 * @minItems 1
 */
export type WeeksAvailable = [string, ...string[]];

/**
 * data/manifest.json: what the latest successful run exported, plus a national KPI summary so the overview can paint before DuckDB-WASM loads.
 */
export interface Manifest {
  files: Files;
  generated_at: GeneratedAt;
  has_fsa_boundaries?: HasFsaBoundaries;
  latest_week: LatestWeek;
  run_id: RunId;
  schema_version?: SchemaVersion;
  summary: Summary;
  weeks_available: WeeksAvailable;
}
export interface ExportFile {
  bytes: Bytes;
  name: Name;
  rows?: Rows;
  sha256: Sha256;
}
export interface SummaryKpi {
  flag: ReportFlag;
  kpi_code: KpiCode;
  prior_week_value?: PriorWeekValue;
  value?: Value;
  wow_pct?: WowPct;
}
