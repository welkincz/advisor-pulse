/* Generated from contracts/schemas/weekly_report.schema.json. Do not edit. */

export type ReportFlag = "UP" | "DOWN" | "FLAT" | "ANOMALY";
export type IsoWeekId = string;
/**
 * KPI codes from PLAN.md §7.
 */
export type KpiCode =
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
export type OrgLevel = "NATIONAL" | "REGION" | "DISTRICT" | "BRANCH";
export type NodeId = string;
export type NodeName = string;
export type ParentId = string | null;
export type PeerCount = number | null;
export type PriorWeekValue = number | null;
/**
 * Dense rank, 1 = best.
 */
export type RankInParent = number | null;
export type Trailing13WAvg = number | null;
export type Value = number | null;
export type WowDelta = number | null;
/**
 * Fraction: 0.042 means +4.2%.
 */
export type WowPct = number | null;

/**
 * mart_weekly_report: long format, one row per (ISO week, node, KPI). Feeds the dashboard, Tableau and the AI narrative.
 */
export interface WeeklyReport {
  flag: ReportFlag;
  iso_week_id: IsoWeekId;
  kpi_code: KpiCode;
  level: OrgLevel;
  node_id: NodeId;
  node_name: NodeName;
  parent_id?: ParentId;
  peer_count?: PeerCount;
  prior_week_value?: PriorWeekValue;
  rank_in_parent?: RankInParent;
  trailing_13w_avg?: Trailing13WAvg;
  value?: Value;
  wow_delta?: WowDelta;
  wow_pct?: WowPct;
}
