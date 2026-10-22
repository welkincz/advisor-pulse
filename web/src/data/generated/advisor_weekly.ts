/* Generated from contracts/schemas/advisor_weekly.schema.json. Do not edit. */

export type ActivitiesCompleted = number;
export type AdvisorId = string;
export type AppointmentsBooked = number;
export type AppointmentsHeld = number;
export type AvgMeetingDurationMin = number | null;
/**
 * As-of branch for the week.
 */
export type BranchId = string;
export type CallsIn = number;
export type CallsOut = number;
export type Conversions = number;
export type DistrictCode = string;
export type IsoWeekId = string;
export type NoShows = number;
/**
 * PRTF_CONTACT_12M denominator.
 */
export type PortfolioClients = number;
/**
 * PRTF_CONTACT_12M numerator.
 */
export type PortfolioContacted12M = number;
/**
 * The lead KPI; null before 12 months of history.
 */
export type PortfolioContactedRate12M = number | null;
/**
 * Regions follow the provinces, as a Canadian bank's branch network usually does.
 */
export type RegionCode = "ON" | "QC" | "BC" | "AB" | "SK" | "MB" | "NS" | "PE" | "NB" | "NL";
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
  branch_id: BranchId;
  calls_in: CallsIn;
  calls_out: CallsOut;
  conversions: Conversions;
  district_code: DistrictCode;
  iso_week_id: IsoWeekId;
  no_shows: NoShows;
  portfolio_clients: PortfolioClients;
  portfolio_contacted_12m: PortfolioContacted12M;
  portfolio_contacted_rate_12m?: PortfolioContactedRate12M;
  region_code: RegionCode;
  unique_clients_contacted: UniqueClientsContacted;
}
