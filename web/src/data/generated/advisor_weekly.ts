/* Generated from contracts/schemas/advisor_weekly.schema.json. Do not edit. */

export type ActivitiesCompleted = number;
export type AdvisorId = string;
export type AppointmentsBooked = number;
export type AppointmentsHeld = number;
export type AvgMeetingDurationMin = number | null;
export type BookSize = number;
/**
 * As-of branch for the week.
 */
export type BranchId = string;
export type CallsIn = number;
export type CallsOut = number;
export type ClientsCovered13W = number;
export type Conversions = number;
export type CoverageRate13W = number | null;
export type DistrictCode = string;
export type IsoWeekId = string;
export type NoShows = number;
export type RegionCode = "ON" | "QC" | "WE" | "AT";
export type UniqueClientsContacted = number;

/**
 * mart_advisor_weekly: one row per advisor and ISO week (last 26 weeks).
 */
export interface AdvisorWeekly {
  activities_completed: ActivitiesCompleted;
  advisor_id: AdvisorId;
  appointments_booked: AppointmentsBooked;
  appointments_held: AppointmentsHeld;
  avg_meeting_duration_min?: AvgMeetingDurationMin;
  book_size: BookSize;
  branch_id: BranchId;
  calls_in: CallsIn;
  calls_out: CallsOut;
  clients_covered_13w: ClientsCovered13W;
  conversions: Conversions;
  coverage_rate_13w?: CoverageRate13W;
  district_code: DistrictCode;
  iso_week_id: IsoWeekId;
  no_shows: NoShows;
  region_code: RegionCode;
  unique_clients_contacted: UniqueClientsContacted;
}
