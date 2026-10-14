/* Generated from contracts/schemas/dq_weekly.schema.json. Do not edit. */

export type DqAction =
  "QUARANTINE" | "FAIL_FILE" | "DEDUPE" | "NORMALIZE" | "MAP_UNKNOWN" | "KEEP_FLAGGED" | "TEST_ERROR" | "RUN_CHECK";
export type IsoWeekId = string;
export type Rate = number | null;
export type RowsAffected = number;
export type RowsInBatch = number;
export type RuleId = string;
export type RuleName = string;

/**
 * mart_dq_weekly: one row per data-quality rule and ISO week.
 */
export interface DqWeekly {
  action: DqAction;
  iso_week_id: IsoWeekId;
  rate?: Rate;
  rows_affected: RowsAffected;
  rows_in_batch: RowsInBatch;
  rule_id: RuleId;
  rule_name: RuleName;
}
