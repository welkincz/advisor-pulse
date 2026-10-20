import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useReducedMotion } from '../../app/useReducedMotion'
import { WARM_UP_WEEKS } from '../../data/usual'
import { domain } from '../charts/scale'

const STEP_MS = 360
const HEIGHT = 44

/**
 * Scrub or play through the weekly runs. The strip behind the handle is a quiet trend of
 * one measure, so the reader can see which part of the history they are standing on.
 * A native range input sits over the strip: drag, click and arrow keys all come for free.
 */
export function WeekPlayer({ weeks, value, onChange, series, label }: {
  weeks: readonly string[]
  value: string
  onChange: (week: string) => void
  /** One value per week, the same length as `weeks`; null leaves a gap. */
  series?: readonly (number | null)[]
  label: string
}) {
  const id = useId()
  const reducedMotion = useReducedMotion()
  const [playing, setPlaying] = useState(false)
  const index = Math.max(0, weeks.indexOf(value))
  const latest = useRef({ index, onChange, weeks })
  latest.current = { index, onChange, weeks }

  useEffect(() => {
    if (!playing) return
    const timer = window.setInterval(() => {
      const { index: at, onChange: change, weeks: all } = latest.current
      if (at >= all.length - 1) { setPlaying(false); return }
      change(all[at + 1]!)
    }, reducedMotion ? STEP_MS * 2 : STEP_MS)
    return () => window.clearInterval(timer)
  }, [playing, reducedMotion])

  const toggle = () => {
    if (!playing && index >= weeks.length - 1) onChange(weeks[Math.max(0, weeks.length - 53)]!)
    setPlaying((on) => !on)
  }

  const { line, area, years } = useMemo(() => strip(weeks, series), [weeks, series])
  const x = weeks.length > 1 ? (index / (weeks.length - 1)) * 1000 : 500

  return <div className="week-player">
    <button type="button" className="week-player-toggle" onClick={toggle} aria-pressed={playing}
      aria-label={playing ? 'Pause the week player' : 'Play through the weeks'}>
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        {playing ? <path d="M4 3h3v10H4zM9 3h3v10H9z" /> : <path d="M4 2.5v11l9-5.5z" />}
      </svg>
    </button>
    <div className="week-player-track">
      <svg className="week-player-strip" viewBox={`0 0 1000 ${HEIGHT}`} preserveAspectRatio="none" aria-hidden="true">
        {area && <path className="week-player-area" d={area} />}
        {line && <path className="week-player-line" d={line} vectorEffect="non-scaling-stroke" />}
        <rect className="week-player-past" x={0} y={0} width={x} height={HEIGHT} />
        <line className="week-player-cursor" x1={x} x2={x} y1={0} y2={HEIGHT} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="week-player-years" aria-hidden="true">
        {years.map((year) => <span key={year.label} style={{ left: `${year.at * 100}%` }}>{year.label}</span>)}
      </div>
      <input id={id} type="range" min={0} max={Math.max(0, weeks.length - 1)} step={1} value={index}
        aria-label={label} aria-valuetext={value}
        onChange={(event) => { setPlaying(false); onChange(weeks[Number(event.target.value)]!) }} />
    </div>
    <output htmlFor={id} className="week-player-value figure-num">{value}</output>
  </div>
}

function strip(weeks: readonly string[], series?: readonly (number | null)[]) {
  const years: { label: string; at: number }[] = []
  weeks.forEach((week, i) => {
    const year = week.slice(0, 4)
    if (i > 0 && year !== weeks[i - 1]!.slice(0, 4)) years.push({ label: year, at: i / Math.max(1, weeks.length - 1) })
  })
  // Fit after the warm-up weeks when there is enough history, so the opening ramp does not flatten the rest.
  const range = series ? domain(series.length > 2 * WARM_UP_WEEKS ? series.slice(WARM_UP_WEEKS) : series, 0) : null
  if (!series || !range || series.filter((v) => v !== null).length < 2) return { line: '', area: '', years }
  const [lo, hi] = range
  const span = hi - lo || 1
  const px = (i: number) => (i / Math.max(1, series.length - 1)) * 1000
  // Warm-up weeks outside the fitted range pin to the strip's edge.
  const py = (v: number) => HEIGHT - 4 - (Math.max(0, Math.min(1, (v - lo) / span))) * (HEIGHT - 10)
  let line = ''
  let area = ''
  let run: string[] = []
  const close = () => {
    if (run.length > 1) area += `M${run[0]!.split(',')[0]},${HEIGHT}L${run.join('L')}L${run.at(-1)!.split(',')[0]},${HEIGHT}Z`
    run = []
  }
  series.forEach((v, i) => {
    if (v === null) { close(); return }
    const point = `${px(i).toFixed(1)},${py(v).toFixed(1)}`
    line += `${run.length ? 'L' : 'M'}${point}`
    run.push(point)
  })
  close()
  return { line, area, years }
}
