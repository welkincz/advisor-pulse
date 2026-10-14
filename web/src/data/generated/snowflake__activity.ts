/* Generated from contracts/schemas/snowflake__activity.schema.json. Do not edit. */

/**
 * Natural key.
 */
export type ActivityId = string;
/**
 * When it happened, or was due (UTC).
 */
export type ActivityTs = string;
export type ActivityType = "CALL_OUT" | "CALL_IN" | "APPOINTMENT" | "REVIEW";
export type AdvisorId = string;
/**
 * For appointments booked on a call: the call's ACTIVITY_ID.
 */
export type BookedFromActivityId = string | null;
/**
 * Branch where the activity was logged.
 */
export type BranchId = string;
export type Channel = "IN_BRANCH" | "PHONE" | "VIDEO";
/**
 * Null for prospecting calls.
 */
export type ClientId = string | null;
export type CreatedTs = string;
export type DurationMin = number | null;
export type Outcome = "NONE" | "FOLLOW_UP" | "PLAN_CREATED" | "PRODUCT_OPENED" | "REFERRAL";
export type ProductLine = "DEPOSITS" | "LENDING" | "MORTGAGE" | "INVESTING" | "INSURANCE";
/**
 * Scheduled time for appointments and reviews (UTC).
 */
export type ScheduledTs = string | null;
export type ActivityStatus = "BOOKED" | "COMPLETED" | "NO_SHOW" | "CANCELLED";
export type UpdatedTs = string;
/**
 * Extract time; the watermark column.
 */
export type ExtractedAt = string;

/**
 * Advisor activity facts, unloaded weekly to sources/snowflake/activity/extract_date=YYYY-MM-DD/part-NNN.parquet.
 */
export interface Snowflake_Activity {
  ACTIVITY_ID: ActivityId;
  ACTIVITY_TS: ActivityTs;
  ACTIVITY_TYPE: ActivityType;
  ADVISOR_ID: AdvisorId;
  BOOKED_FROM_ACTIVITY_ID?: BookedFromActivityId;
  BRANCH_ID: BranchId;
  CHANNEL: Channel;
  CLIENT_ID?: ClientId;
  CREATED_TS: CreatedTs;
  DURATION_MIN?: DurationMin;
  OUTCOME?: Outcome | null;
  PRODUCT_LINE?: ProductLine | null;
  SCHEDULED_TS?: ScheduledTs;
  STATUS: ActivityStatus;
  UPDATED_TS: UpdatedTs;
  _EXTRACTED_AT: ExtractedAt;
}
