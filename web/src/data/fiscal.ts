/**
 * The fiscal calendar (PLAN.md §6.8): the year starts on 1 November, as at Canadian banks.
 * FY26 runs from 2025-11-01 to 2026-10-31; Q1 is Nov–Jan, Q2 Feb–Apr, Q3 May–Jul, Q4 Aug–Oct.
 * A week counts in the quarter that holds its ISO week's Sunday. The same rules live in
 * dbt (dbt/macros/dates.sql) and Python (src/pulse/fiscal.py), pinned by the same cases.
 */

const FIRST_MONTH = 11
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** The Sunday that ends an ISO week, as a UTC date. */
export function weekSunday(isoWeek: string): Date {
  const year = Number(isoWeek.slice(0, 4))
  const week = Number(isoWeek.slice(6))
  const jan4 = new Date(Date.UTC(year, 0, 4))
  const monday = Date.UTC(year, 0, 4 - ((jan4.getUTCDay() + 6) % 7))
  return new Date(monday + ((week - 1) * 7 + 6) * 86_400_000)
}

export function fiscalYear(day: Date): number {
  return day.getUTCFullYear() + (day.getUTCMonth() + 1 >= FIRST_MONTH ? 1 : 0)
}

export function fiscalQuarter(day: Date): number {
  return Math.floor(((day.getUTCMonth() + 1 - FIRST_MONTH + 12) % 12) / 3) + 1
}

/** 'FY26-Q1' for 2025-11-01. */
export function fiscalQuarterId(day: Date): string {
  return `FY${String(fiscalYear(day) % 100).padStart(2, '0')}-Q${fiscalQuarter(day)}`
}

/** The quarter a week reports in: the one holding its Sunday. */
export function weekFiscalQuarterId(isoWeek: string): string {
  return fiscalQuarterId(weekSunday(isoWeek))
}

/** 'FY26' for any week whose Sunday falls between 2025-11-01 and 2026-10-31. */
export function weekFiscalYear(isoWeek: string): string {
  return weekFiscalQuarterId(isoWeek).slice(0, 4)
}

/** 'FY26-Q1' → 'Q1 FY26', the order a bank's quarterly report uses. */
export function quarterLabel(quarterId: string): string {
  return `${quarterId.slice(5)} ${quarterId.slice(0, 4)}`
}

/** 'Nov 2025 – Jan 2026' from the quarter's first and last day (ISO dates). */
export function quarterMonths(start: string, end: string): string {
  const month = (iso: string) => `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`
  return `${month(start)} – ${month(end)}`
}

/** The same quarter one fiscal year earlier: 'FY27-Q1' → 'FY26-Q1'. */
export function yearEarlier(quarterId: string): string {
  return `FY${String(Number(quarterId.slice(2, 4)) - 1).padStart(2, '0')}${quarterId.slice(4)}`
}

/** The quarter before: 'FY27-Q1' → 'FY26-Q4'. */
export function quarterBefore(quarterId: string): string {
  const q = Number(quarterId.slice(-1))
  return q > 1 ? `${quarterId.slice(0, 6)}${q - 1}` : `${yearEarlier(quarterId).slice(0, 6)}4`
}
