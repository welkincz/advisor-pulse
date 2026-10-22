/* Generated from contracts/schemas/org_weekly.schema.json. Do not edit. */

export type ActiveAdvisors = number;
export type ActivitiesCompleted = number;
export type ActivitiesPerAdvisor = number | null;
export type AppointmentsBooked = number;
export type AppointmentsHeld = number;
export type AvgMeetingDurationMin = number | null;
export type CallToApptRate = number | null;
export type CallsIn = number;
export type CallsOut = number;
export type ConversionRate = number | null;
export type Conversions = number;
export type IsoWeekId = string;
export type OrgLevel = "NATIONAL" | "REGION" | "DISTRICT" | "BRANCH";
export type NoShows = number;
/**
 * 'CA' for national; region, district or branch code.
 */
export type NodeId = string;
export type NodeName = string;
/**
 * Null for the national node.
 */
export type ParentId = string | null;
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
export type ShowRate = number | null;
export type UniqueClientsContacted = number;

/**
 * mart_org_weekly: one row per hierarchy node and ISO week, every level. Ratios are recomputed from summed parts, never averaged.
 */
export interface OrgWeekly {
  active_advisors: ActiveAdvisors;
  activities_completed: ActivitiesCompleted;
  activities_per_advisor?: ActivitiesPerAdvisor;
  appointments_booked: AppointmentsBooked;
  appointments_held: AppointmentsHeld;
  avg_meeting_duration_min?: AvgMeetingDurationMin;
  call_to_appt_rate?: CallToApptRate;
  calls_in: CallsIn;
  calls_out: CallsOut;
  conversion_rate?: ConversionRate;
  conversions: Conversions;
  iso_week_id: IsoWeekId;
  level: OrgLevel;
  no_shows: NoShows;
  node_id: NodeId;
  node_name: NodeName;
  parent_id?: ParentId;
  portfolio_clients: PortfolioClients;
  portfolio_contacted_12m: PortfolioContacted12M;
  portfolio_contacted_rate_12m?: PortfolioContactedRate12M;
  show_rate?: ShowRate;
  unique_clients_contacted: UniqueClientsContacted;
}
