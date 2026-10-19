/** Short labels from PLAN.md §8. An absent export row means unreported, not zero. */
export const RULES = [
  { id: 'DQ001', description: 'Null activity ID', action: 'Quarantine row' },
  { id: 'DQ002', description: 'Enum outside the activity contract', action: 'Quarantine row' },
  { id: 'DQ003', description: 'Duration outside 0–480 minutes', action: 'Quarantine row' },
  { id: 'DQ004', description: 'Activity timestamp outside allowed range', action: 'Quarantine row' },
  { id: 'DQ005', description: 'Unparseable date or integer', action: 'Quarantine row' },
  { id: 'DQ006', description: 'Missing required column or type change', action: 'Fail file; additive column warns' },
  { id: 'DQ010', description: 'Exact duplicate or re-sent row', action: 'Dedupe and count' },
  { id: 'DQ011', description: 'Postal code invalid after normalization', action: 'Map FSA to UNK; warn above 10%' },
  { id: 'DQ012', description: 'Advisor absent from master', action: 'Map to Unknown; warn above 0.5%, fail above 2%' },
  { id: 'DQ013', description: 'Client absent from master', action: 'Keep null client key; warn above 1%' },
  { id: 'DQ020', description: 'SCD2 range overlap, gap, or multiple current rows', action: 'dbt test error' },
  { id: 'DQ021', description: 'Mart key or relationship failure', action: 'dbt test error' },
  { id: 'DQ022', description: 'Child roll-up differs from parent', action: 'dbt test error' },
  { id: 'DQ023', description: 'Ratio outside 0–1', action: 'dbt test error' },
  { id: 'DQ030', description: 'Activity freshness within two days of week end', action: 'Fail run' },
  { id: 'DQ031', description: 'Calendar-adjusted completed activity volume vs trailing eight weeks', action: 'Warn beyond 3σ and 5%; fail beyond 50%' },
  { id: 'DQ032', description: 'Quarantine rate over 2% of batch', action: 'Fail run' },
  { id: 'DQ033', description: 'Quarantined rows vs injected defect manifest', action: 'Fail in CI; warn in weekly run' },
] as const

export const RULES_URL = 'https://github.com/welkincz/advisor-pulse/blob/main/docs/PLAN.md#8-data-quality-rules'
