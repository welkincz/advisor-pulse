import { Link } from 'react-router-dom'
import { Delta, Explain } from '../../components/primitives'
import { KPI_LABELS, happened, formatKpi, useNarrative } from '../../data'
import type { Better } from '../../data/glossary'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { REGION_ORDER } from '../../data/regions'
import { usualStep, versusUsual } from '../../data/usual'
import { DIVERGING } from '../../theme/tokens'

const SPLIT = DIVERGING.map((name) => `var(--${name})`)

/** `away` is the share from usual; null before 13 weeks, or when the usual is 0 and there is nothing to divide by. */
export interface Moved { id: string; name: string; row: WeeklyReport | undefined; away: number | null; settled: boolean }

/** Each region's row for the week, best against its own usual week first; regions with no usual yet last. */
export function movedRows(regions: readonly WeeklyReport[], code: KpiCode, week: string, better: Better, settled: boolean): Moved[] {
  const good = (away: number | null) => away === null ? -Infinity : better === 'lower' ? -away : away
  return REGION_ORDER.flatMap((id) => {
    const row = regions.find((r) => r.node_id === id && r.kpi_code === code && r.iso_week_id === week)
    const name = row?.node_name ?? regions.find((r) => r.node_id === id)?.node_name
    if (!name) return []
    return [{ id, name, row, away: row && settled ? versusUsual(row) : null, settled }]
  }).sort((a, b) => good(b.away) - good(a.away) || a.name.localeCompare(b.name))
}

/** The bar, -1 to 1 of half the track: better grows right, worse left; raw direction when neither is better. */
export function barShare(away: number | null, reach: number, better: Better): number {
  const raw = away === null ? 0 : Math.max(-1, Math.min(1, away / reach))
  return better === 'lower' ? -raw : raw
}

function MovedRow({ item, code, week, better, reach, href }: { item: Moved; code: KpiCode; week: string; better: Better; reach: number; href: string }) {
  // The region's run summary for its card; empty when the run published none.
  const narrative = useNarrative(week, item.id)
  const summary = narrative.status === 'ready' ? narrative.data.headline : null
  const { row, away } = item
  const share = barShare(away, reach, better)
  const step = usualStep(away, reach, better === 'lower')
  const card = () => ({
    title: item.name,
    value: formatKpi(code, row?.value),
    // The usual itself, whenever the week is settled: a 0% usual still compares (in points).
    happened: happened({ code, value: row?.value, wow: row?.wow_pct, usual: item.settled ? row?.trailing_13w_avg ?? null : null, flag: row?.flag === 'ANOMALY', better }),
    answer: summary ? { q: 'The run summary', a: summary } : undefined,
    hint: `Click to open the ${item.name} report.`,
  })
  return <li className="moved-row">
    <Explain block card={card}>{(described) => <Link to={href} className="moved-link" {...described}>
      <span className="moved-name">{item.name}</span>
      <span className="moved-track" aria-hidden="true">
        <i className="moved-mid" />
        <i className={`moved-bar${share < 0 ? ' is-below' : ''}`} style={{ inlineSize: `${Math.abs(share) * 50}%`, background: step === null ? undefined : SPLIT[step] }} />
      </span>
      <span className="moved-away figure-num">{away === null ? '–' : `${away > 0 ? '+' : away < 0 ? '−' : '±'}${Math.abs(away * 100).toFixed(1)}%`}<span className="moved-away-unit"> vs usual</span></span>
      <span className="moved-value figure-num">{formatKpi(code, row?.value)}</span>
      <Delta value={row?.wow_pct} better={better} />
    </Link>}</Explain>
  </li>
}

/**
 * This week's regions against their own usual week, best first: the ranking the region notes
 * used to spell out in paragraphs. Bars grow from the usual-week line in the middle and slide
 * to their new length when the week or the measure changes.
 */
export function WhatMoved({ regions, code, week, better, settled, hrefFor }: {
  regions: readonly WeeklyReport[]
  code: KpiCode
  week: string
  better: Better
  settled: boolean
  hrefFor: (id: string) => string
}) {
  const rows = movedRows(regions, code, week, better, settled)
  const reach = Math.max(0.01, ...rows.map((r) => Math.abs(r.away ?? 0)))
  return <div className="moved">
    <p className="moved-scale" aria-hidden="true">{better === 'neither'
      ? <><span>Below usual</span><span>Usual</span><span>Above usual</span></>
      : <><span>Worse than usual</span><span>Usual</span><span>Better than usual</span></>}
      <span className="moved-col moved-col-away">vs usual</span><span className="moved-col moved-col-value">This week</span><span className="moved-col moved-col-wow">vs last week</span></p>
    <ol className="moved-rows" aria-label={`${KPI_LABELS[code]} by region, ${week}, against each region's usual week, best first`}>
      {rows.map((item) => <MovedRow key={item.id} item={item} code={code} week={week} better={better} reach={reach} href={hrefFor(item.id)} />)}
    </ol>
  </div>
}
