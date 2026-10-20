/** Monday of an ISO week ("2026-W42"), as a UTC date. */
export function isoWeekMonday(id: string): Date | null {
  const match = /^(\d{4})-W(\d{2})$/.exec(id)
  if (!match) return null
  const year = Number(match[1])
  const week = Number(match[2])
  // 4 January is always in week 1; step back to its Monday, then forward.
  const jan4 = new Date(Date.UTC(year, 0, 4))
  const monday = new Date(jan4)
  monday.setUTCDate(jan4.getUTCDate() - ((jan4.getUTCDay() + 6) % 7) + (week - 1) * 7)
  return monday
}

/** "October 12 to 18, 2026", matching the "Oct 5, 2026" dates elsewhere in the report. */
export function weekSpan(id: string): string {
  const monday = isoWeekMonday(id)
  if (!monday) return id
  const sunday = new Date(monday)
  sunday.setUTCDate(monday.getUTCDate() + 6)
  const month = (date: Date) => date.toLocaleDateString('en-CA', { timeZone: 'UTC', month: 'long' })
  const [m1, d1, y1] = [month(monday), monday.getUTCDate(), monday.getUTCFullYear()]
  const [m2, d2, y2] = [month(sunday), sunday.getUTCDate(), sunday.getUTCFullYear()]
  if (y1 !== y2) return `${m1} ${d1}, ${y1} to ${m2} ${d2}, ${y2}`
  if (m1 !== m2) return `${m1} ${d1} to ${m2} ${d2}, ${y2}`
  return `${m1} ${d1} to ${d2}, ${y2}`
}
