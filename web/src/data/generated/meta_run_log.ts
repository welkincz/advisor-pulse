/* Generated from contracts/schemas/meta.run_log.schema.json. Do not edit. */

export type Attempt = number;
export type DurationMs = number | null;
export type EndedAt = string | null;
export type GitSha = string | null;
export type IsoWeekId = string;
export type Message = string | null;
export type RowsIn = number | null;
export type RowsOut = number | null;
export type RowsQuarantined = number | null;
export type RunId = string;
export type RunType = "WEEKLY" | "BACKFILL" | "MANUAL";
export type Stage = string;
export type StartedAt = string;
export type StageStatus = "RUNNING" | "SUCCESS" | "WARN" | "FAILED" | "SKIPPED";

/**
 * One row per stage attempt.
 */
export interface MetaRunLog {
  attempt: Attempt;
  duration_ms?: DurationMs;
  ended_at?: EndedAt;
  git_sha?: GitSha;
  iso_week_id: IsoWeekId;
  message?: Message;
  rows_in?: RowsIn;
  rows_out?: RowsOut;
  rows_quarantined?: RowsQuarantined;
  run_id: RunId;
  run_type: RunType;
  stage: Stage;
  started_at: StartedAt;
  status: StageStatus;
}
