/* Generated from contracts/schemas/narrative.schema.json. Do not edit. */

export type GeneratedAt = string;
export type IsoWeekId = string;
/**
 * @minItems 1
 */
export type Bullets = [NarrativeBullet, ...NarrativeBullet[]];
/**
 * Every bullet cites at least one fact.
 *
 * @minItems 1
 */
export type FactIds = [string, ...string[]];
export type Text = string;
/**
 * @minItems 1
 */
export type FactsUsed = [NarrativeFact, ...NarrativeFact[]];
export type FactId = string;
export type IsoWeekId1 = string;
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
export type NodeId = string;
export type PeerCount = number | null;
export type PriorWeekValue = number | null;
export type RankInParent = number | null;
export type Trailing13WAvg = number | null;
export type Value = number | null;
export type WowPct = number | null;
export type Fallback = boolean;
export type Headline = string;
export type OrgLevel = "NATIONAL" | "REGION" | "DISTRICT" | "BRANCH";
/**
 * Null for template fallbacks.
 */
export type Model = string | null;
export type NodeId1 = string;
export type PromptVersion = string;
export type Validated = boolean;
/**
 * @minItems 1
 */
export type FactIds1 = [string, ...string[]];
export type NodeId2 = string;
export type Reason = string;
export type Watchlist = WatchItem[];
export type Narratives = NodeNarrative[];
export type SchemaVersion = string;

/**
 * data/narratives/YYYY-Www.json: one narrative per region and district.
 */
export interface Narrative {
  generated_at: GeneratedAt;
  iso_week_id: IsoWeekId;
  narratives: Narratives;
  schema_version?: SchemaVersion;
}
export interface NodeNarrative {
  bullets: Bullets;
  facts_used: FactsUsed;
  fallback: Fallback;
  headline: Headline;
  level: OrgLevel;
  model?: Model;
  node_id: NodeId1;
  prompt_version: PromptVersion;
  validated: Validated;
  watchlist?: Watchlist;
}
export interface NarrativeBullet {
  fact_ids: FactIds;
  text: Text;
}
export interface NarrativeFact {
  fact_id: FactId;
  iso_week_id: IsoWeekId1;
  kpi_code: KpiCode;
  node_id: NodeId;
  peer_count?: PeerCount;
  prior_week_value?: PriorWeekValue;
  rank_in_parent?: RankInParent;
  trailing_13w_avg?: Trailing13WAvg;
  value?: Value;
  wow_pct?: WowPct;
}
export interface WatchItem {
  fact_ids: FactIds1;
  node_id: NodeId2;
  reason: Reason;
}
