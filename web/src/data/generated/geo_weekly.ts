/* Generated from contracts/schemas/geo_weekly.schema.json. Do not edit. */

export type ActiveClients = number;
export type ActivitiesCompleted = number;
export type ClientsContacted13W = number;
export type CoverageRate13W = number | null;
export type DistrictCode = string;
export type FsaCode = string;
export type IsoWeekId = string;

/**
 * mart_geo_weekly: one row per FSA and ISO week (last 13 weeks).
 */
export interface GeoWeekly {
  active_clients: ActiveClients;
  activities_completed: ActivitiesCompleted;
  clients_contacted_13w: ClientsContacted13W;
  coverage_rate_13w?: CoverageRate13W;
  district_code: DistrictCode;
  fsa_code: FsaCode;
  iso_week_id: IsoWeekId;
}
