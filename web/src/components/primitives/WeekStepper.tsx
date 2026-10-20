/**
 * The report week: previous and next buttons around a select of every weekly run, and a way
 * back to the latest. The week lives in the URL, so the caller owns it.
 */
export function WeekStepper({ weeks, week, latest, onWeek }: { weeks: readonly string[]; week: string; latest: string; onWeek: (week: string) => void }) {
  const at = weeks.indexOf(week)
  return <nav className="stepper" aria-label="Report week">
    <button type="button" onClick={() => onWeek(weeks[at - 1]!)} disabled={at <= 0} aria-label="Previous week">
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M10 3 5 8l5 5" /></svg>
    </button>
    <select className="stepper-week figure-num" aria-label="Week" value={week} onChange={(event) => onWeek(event.target.value)}>
      {[...weeks].reverse().map((w) => <option key={w} value={w}>{w}{w === latest ? ' (latest)' : ''}</option>)}
    </select>
    <button type="button" onClick={() => onWeek(weeks[at + 1]!)} disabled={at >= weeks.length - 1} aria-label="Next week">
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="m6 3 5 5-5 5" /></svg>
    </button>
    {week !== latest && <button type="button" className="stepper-latest" onClick={() => onWeek(latest)}>Latest week</button>}
  </nav>
}
