/**
 * The regions of reference/org.yaml in display order (largest branch network first).
 * Regions follow the provinces, as a Canadian bank's network usually does, so a region
 * missing from an export is still named rather than left blank.
 */
export const REGIONS: readonly (readonly [code: string, name: string])[] = [
  ['ON', 'Ontario'],
  ['QC', 'Quebec'],
  ['BC', 'British Columbia'],
  ['AB', 'Alberta'],
  ['SK', 'Saskatchewan'],
  ['MB', 'Manitoba'],
  ['NS', 'Nova Scotia'],
  ['NB', 'New Brunswick'],
  ['NL', 'Newfoundland and Labrador'],
  ['PE', 'Prince Edward Island'],
]

export const REGION_ORDER: readonly string[] = REGIONS.map(([code]) => code)
