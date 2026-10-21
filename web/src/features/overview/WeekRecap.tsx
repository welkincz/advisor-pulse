import { useEffect, useState } from 'react'

/** The parts of the recap JSON (src/pulse/export/recap.py) the page reads for the transcript. */
export interface Recap {
  week: string
  headline: string
  support: string
  kpis: { label: string; text: string; flag: boolean }[]
  flagged: { name: string; label: string }[]
  summary: string | null
}

const base = `${import.meta.env.BASE_URL}recap/`

/** The weekly run's recap, or null when this build has none (it is optional: a failed render ships without it). */
export function useRecap(): Recap | null {
  const [recap, setRecap] = useState<Recap | null>(null)
  useEffect(() => {
    let live = true
    fetch(`${base}recap.json`)
      .then((response) => (response.ok ? response.json() as Promise<Recap> : null))
      .then((data) => { if (live && data && typeof data.week === 'string') setRecap(data) })
      .catch(() => undefined)
    return () => { live = false }
  }, [])
  return recap
}

/**
 * The week in 20 seconds, rendered by the weekly run (video/). It never plays on its own, so
 * reduced motion needs nothing more; the transcript says everything the video shows.
 */
export function WeekRecap({ recap }: { recap: Recap }) {
  return <div className="recap">
    <video className="recap-video" controls muted playsInline preload="none" poster={`${base}poster.jpg`}
      aria-label={`The week in 20 seconds, ${recap.week}`} aria-describedby="recap-transcript">
      <source src={`${base}recap.mp4`} type="video/mp4" />
    </video>
    <details className="recap-transcript" id="recap-transcript">
      <summary>What the video shows</summary>
      <p>{recap.headline} {recap.support}</p>
      <p>{recap.kpis.map((k) => `${k.label} ${k.text}${k.flag ? ' (anomaly)' : ''}`).join('; ')}.</p>
      {recap.flagged.length > 0 && <p>Biggest regional anomalies: {recap.flagged.map((f) => `${f.name}, ${f.label.toLowerCase()}`).join('; ')}.</p>}
      {recap.summary && <p>{recap.summary}</p>}
    </details>
  </div>
}
