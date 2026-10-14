/* Generated from contracts/schemas/run_log.schema.json. Do not edit. */

export type GeneratedAt = string;
/**
 * @maxItems 12
 */
export type Runs =
  | []
  | [RunSummary]
  | [RunSummary, RunSummary]
  | [RunSummary, RunSummary, RunSummary]
  | [RunSummary, RunSummary, RunSummary, RunSummary]
  | [RunSummary, RunSummary, RunSummary, RunSummary, RunSummary]
  | [RunSummary, RunSummary, RunSummary, RunSummary, RunSummary, RunSummary]
  | [RunSummary, RunSummary, RunSummary, RunSummary, RunSummary, RunSummary, RunSummary]
  | [RunSummary, RunSummary, RunSummary, RunSummary, RunSummary, RunSummary, RunSummary, RunSummary]
  | [RunSummary, RunSummary, RunSummary, RunSummary, RunSummary, RunSummary, RunSummary, RunSummary, RunSummary]
  | [
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary
    ]
  | [
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary
    ]
  | [
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary,
      RunSummary
    ];
export type CheckId = string;
export type Expected = string | null;
export type Message = string | null;
export type Observed = number | null;
export type CheckSeverity = "WARN" | "FAIL";
export type CheckStatus = "PASS" | "WARN" | "FAIL";
export type Checks = RunCheck[];
export type DurationMs = number | null;
export type EndedAt = string | null;
export type GitSha = string | null;
export type IsoWeekId = string;
export type RunId = string;
export type RunType = "WEEKLY" | "BACKFILL" | "MANUAL";
export type Attempt = number;
export type DurationMs1 = number | null;
export type EndedAt1 = string | null;
export type Message1 = string | null;
export type RowsIn = number | null;
export type RowsOut = number | null;
export type RowsQuarantined = number | null;
export type Stage = string;
export type StartedAt = string;
export type StageStatus = "RUNNING" | "SUCCESS" | "WARN" | "FAILED" | "SKIPPED";
export type Stages = StageAttempt[];
export type StartedAt1 = string;
/**
 * Worst stage status of the run.
 */
export type StageStatus1 = "RUNNING" | "SUCCESS" | "WARN" | "FAILED" | "SKIPPED";
export type SchemaVersion = string;

/**
 * data/run_log.json: the last 12 runs, newest first. Deployed even when a run fails.
 */
export interface RunLog {
  generated_at: GeneratedAt;
  runs: Runs;
  schema_version?: SchemaVersion;
}
export interface RunSummary {
  checks: Checks;
  duration_ms?: DurationMs;
  ended_at?: EndedAt;
  git_sha?: GitSha;
  iso_week_id: IsoWeekId;
  run_id: RunId;
  run_type: RunType;
  stages: Stages;
  started_at: StartedAt1;
  status: StageStatus1;
}
export interface RunCheck {
  check_id: CheckId;
  expected?: Expected;
  message?: Message;
  observed?: Observed;
  severity: CheckSeverity;
  status: CheckStatus;
}
export interface StageAttempt {
  attempt: Attempt;
  duration_ms?: DurationMs1;
  ended_at?: EndedAt1;
  message?: Message1;
  rows_in?: RowsIn;
  rows_out?: RowsOut;
  rows_quarantined?: RowsQuarantined;
  stage: Stage;
  started_at: StartedAt;
  status: StageStatus;
}
