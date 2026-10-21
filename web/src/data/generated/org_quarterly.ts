/* Generated from contracts/schemas/org_quarterly.schema.json. Do not edit. */

export type ActivitiesCompleted = number;
export type ActivitiesPerAdvisor = number | null;
export type AdvisorWeeks = number;
export type AppointmentsBooked = number;
export type AppointmentsHeld = number;
export type AvgMeetingDurationMin = number | null;
export type BookSize = number;
export type BookedFromCall = number;
export type CallToApptRate = number | null;
export type CallsIn = number;
export type CallsOut = number;
export type ClientsCovered13W = number;
export type ConversionRate = number | null;
export type Conversions = number;
export type CoverageRate13W = number | null;
export type FirstWeek = string;
export type FiscalQuarter = number;
/**
 * e.g. 'FY26-Q1'.
 */
export type FiscalQuarterId = string;
export type FiscalYear = number;
/**
 * False for a quarter to date or a partial first quarter.
 */
export type IsComplete = boolean;
/**
 * Stocks (book, coverage) are taken at this week.
 */
export type LastWeek = string;
export type OrgLevel = "NATIONAL" | "REGION" | "DISTRICT" | "BRANCH";
export type NoShows = number;
export type NodeId = string;
export type NodeName = string;
export type ParentId = string | null;
export type QuarterEnd = string;
export type QuarterStart = string;
export type ShowRate = number | null;
export type UniqueClientsContacted = number;
export type WeeksInQuarter = number;
export type WeeksReported = number;

/**
 * mart_org_quarterly: one row per hierarchy node and fiscal quarter (the fiscal year starts 1 November). Flows are summed, distinct clients counted over the quarter, stocks taken at the last reported week, ratios rebuilt from parts.
 */
export interface OrgQuarterly {
  activities_completed: ActivitiesCompleted;
  activities_per_advisor?: ActivitiesPerAdvisor;
  advisor_weeks: AdvisorWeeks;
  appointments_booked: AppointmentsBooked;
  appointments_held: AppointmentsHeld;
  avg_meeting_duration_min?: AvgMeetingDurationMin;
  book_size: BookSize;
  booked_from_call: BookedFromCall;
  call_to_appt_rate?: CallToApptRate;
  calls_in: CallsIn;
  calls_out: CallsOut;
  clients_covered_13w: ClientsCovered13W;
  conversion_rate?: ConversionRate;
  conversions: Conversions;
  coverage_rate_13w?: CoverageRate13W;
  first_week: FirstWeek;
  fiscal_quarter: FiscalQuarter;
  fiscal_quarter_id: FiscalQuarterId;
  fiscal_year: FiscalYear;
  is_complete: IsComplete;
  last_week: LastWeek;
  level: OrgLevel;
  no_shows: NoShows;
  node_id: NodeId;
  node_name: NodeName;
  parent_id?: ParentId;
  quarter_end: QuarterEnd;
  quarter_start: QuarterStart;
  show_rate?: ShowRate;
  unique_clients_contacted: UniqueClientsContacted;
  weeks_in_quarter: WeeksInQuarter;
  weeks_reported: WeeksReported;
}
