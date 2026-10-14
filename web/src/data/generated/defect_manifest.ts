/* Generated from contracts/schemas/defect_manifest.schema.json. Do not edit. */

export type DqAction =
  "QUARANTINE" | "FAIL_FILE" | "DEDUPE" | "NORMALIZE" | "MAP_UNKNOWN" | "KEEP_FLAGGED" | "TEST_ERROR" | "RUN_CHECK";
/**
 * Source column the defect is in.
 */
export type Column = string | null;
export type Detail = string;
/**
 * What the pipeline should produce: normalized postal code or 'UNK', final status, activity week of a late row, new branch or role.
 */
export type ExpectedValue = string | null;
/**
 * Path relative to the sources root.
 */
export type File = string;
/**
 * Week of the batch that carries the defect.
 */
export type IsoWeekId = string;
export type DefectKind =
  | "EXACT_DUPLICATE"
  | "RESENT_UPDATE"
  | "NULL_ACTIVITY_ID"
  | "INVALID_ENUM"
  | "DURATION_OUT_OF_RANGE"
  | "ACTIVITY_TS_OUT_OF_RANGE"
  | "UNPARSEABLE_VALUE"
  | "UNKNOWN_ADVISOR"
  | "DIRTY_POSTAL_CODE"
  | "LATE_ARRIVING"
  | "ADVISOR_TRANSFER"
  | "ADVISOR_PROMOTION"
  | "ADVISOR_TERM"
  | "CLIENT_REASSIGNMENT";
/**
 * ACTIVITY_ID, CLNT_ID or ASGN_ID of the row, when it has one.
 */
export type NaturalKey = string | null;
/**
 * The value as written, as text.
 */
export type RawValue = string | null;
/**
 * 0-based data row in the file (header excluded); null for SQLite tables.
 */
export type Row = number | null;
/**
 * DQ rule that must catch it.
 */
export type RuleId = string | null;
/**
 * 'snowflake' or 'teradata'.
 */
export type Source = string;
/**
 * Source table, e.g. 'activity', 'CLNT'.
 */
export type TableName = string;
export type Defects = Defect[];
export type GeneratedAt = string;
/**
 * @minItems 1
 */
export type IsoWeeks = [string, ...string[]];
export type SchemaVersion = string;
export type Seed = number;

/**
 * Ground truth of injected defects: defects/YYYY-Www.json from the generator, fixtures/defects.json for the fixtures.
 */
export interface DefectManifest {
  defects: Defects;
  generated_at: GeneratedAt;
  iso_weeks: IsoWeeks;
  schema_version?: SchemaVersion;
  seed: Seed;
}
export interface Defect {
  /**
   * Expected handling.
   */
  action?: DqAction | null;
  column?: Column;
  detail: Detail;
  expected_value?: ExpectedValue;
  file: File;
  iso_week_id: IsoWeekId;
  kind: DefectKind;
  natural_key?: NaturalKey;
  raw_value?: RawValue;
  row?: Row;
  rule_id?: RuleId;
  source: Source;
  table_name: TableName;
}
