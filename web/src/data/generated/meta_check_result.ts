/* Generated from contracts/schemas/meta.check_result.schema.json. Do not edit. */

export type CheckId = string;
/**
 * Threshold or range, as text.
 */
export type Expected = string | null;
export type Message = string | null;
export type Observed = number | null;
export type RunId = string;
export type CheckSeverity = "WARN" | "FAIL";
export type CheckStatus = "PASS" | "WARN" | "FAIL";

/**
 * One row per run check (DQ030–DQ033).
 */
export interface MetaCheckResult {
  check_id: CheckId;
  expected?: Expected;
  message?: Message;
  observed?: Observed;
  run_id: RunId;
  severity: CheckSeverity;
  status: CheckStatus;
}
