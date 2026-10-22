/* Generated from contracts/schemas/portfolio_weekly.schema.json. Do not edit. */

/**
 * Holder at week end.
 */
export type AdvisorId = string;
/**
 * Transit.
 */
export type BranchId = string;
export type Clients = number;
export type Contacted12M = number;
/**
 * PRTF_CONTACT_12M; null before 12 months of history.
 */
export type ContactedRate12M = number | null;
export type DistrictCode = string;
/**
 * Where the holder works at week end; differs from branch_id under DQ025.
 */
export type HolderBranchId = string | null;
export type IsoWeekId = string;
export type PortfolioId = string;
/**
 * Regions follow the provinces, as a Canadian bank's branch network usually does.
 */
export type RegionCode = "ON" | "QC" | "BC" | "AB" | "SK" | "MB" | "NS" | "PE" | "NB" | "NL";

/**
 * mart_portfolio_weekly: one row per portfolio and ISO week (last 26 weeks), under the holder at week end and the transit branch; the lead KPI per portfolio.
 */
export interface PortfolioWeekly {
  advisor_id: AdvisorId;
  branch_id: BranchId;
  clients: Clients;
  contacted_12m: Contacted12M;
  contacted_rate_12m?: ContactedRate12M;
  district_code: DistrictCode;
  holder_branch_id?: HolderBranchId;
  iso_week_id: IsoWeekId;
  portfolio_id: PortfolioId;
  region_code: RegionCode;
}
