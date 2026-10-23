import { useEffect, useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { TrendChart } from '../components/charts/TrendChart'
import { Delta, Explain, Section, SeriesCsvButton, Term, WeekStepper } from '../components/primitives'
import { DataNotice, KPI_LABELS, KPI_PLAIN, TERMS, defaultLead, formatKpi, formatWow, happened, leadFor, useChildReportHistory, useLevelKpiHistory, useManifest, useOrgWeekly, usePulseData, useWeeklyReportHistory } from '../data'
import type { Manifest } from '../data/generated/manifest'
import type { KpiCode, WeeklyReport } from '../data/generated/weekly_report'
import { WARM_UP_WEEKS, settledWeeks } from '../data/usual'
import { resolveWeek } from '../features/drill/path'
import { Funnel, funnelFor } from '../features/overview/Funnel'
import { nodeHeadline } from '../features/overview/headline'
import { type BoardRow, KpiBoard, boardRows } from '../features/overview/KpiBoard'
import { KPI_CODES, KPI_DEFINITIONS, LOWER_IS_BETTER } from '../features/overview/kpis'
import { RegionMultiples } from '../features/overview/RegionMultiples'
import { WeekRecap, useRecap } from '../features/overview/WeekRecap'
import { WhatMoved } from '../features/overview/WhatMoved'
import { RunStatusBanner } from '../features/overview/RunStatusBanner'
import { WeekHeatmap } from '../features/overview/WeekHeatmap'
import { heroChartHeight, useMedia } from '../features/overview/useMedia'
import { weekSpan } from '../features/overview/week'
import { QuarterPanel } from '../features/quarters/QuarterPanel'
import '../features/overview/overview.css'

const MULTIPLE_WEEKS = 26
/** Batch-level rates: the marts publish them for Canada only, so there is no regional split. */
const NATIONAL_ONLY = new Set<KpiCode>(['LATE_RATE', 'QUAR_RATE'])

/** Board rows from the manifest summary: the latest week paints before DuckDB-WASM loads. */
function summaryRows(manifest: Manifest): Map<KpiCode, BoardRow> {
  return new Map(manifest.summary.map((row) => [row.kpi_code, { value: row.value ?? null, wow: row.wow_pct ?? null, flag: row.flag === 'ANOMALY', trend: [] }]))
}

function Briefing({ manifest }: { manifest: Manifest }) {
  const [search, setSearch] = useSearchParams()
  const weeks = manifest.weeks_available
  const latest = manifest.latest_week
  const week = resolveWeek(search.get('week'), weeks)!
  const requested = search.get('kpi') as KpiCode | null
  const history = useWeeklyReportHistory('CA', weeks)
  const all = useMemo<WeeklyReport[]>(() => (history.status === 'ready' ? history.data : []), [history])
  const ready = history.status === 'ready'
  // The chart opens on the measure the title sentence is about: for the latest week the
  // summary's lead, for an earlier one that week's lead once the history has loaded (activities
  // per advisor in a week without 12 months of history behind it).
  const lead = ready && week !== latest ? leadFor(all, week) : defaultLead(manifest.summary)
  const code: KpiCode = requested && KPI_CODES.includes(requested) ? requested : lead
  const set = (key: 'week' | 'kpi', value: string) => {
    const next = new URLSearchParams(search)
    if (value === (key === 'week' ? latest : lead)) next.delete(key)
    else next.set(key, value)
    setSearch(next, { replace: true })
  }

  const regions = useChildReportHistory('CA', weeks)
  const org = useOrgWeekly('CA', [week])
  const heatRegions = useLevelKpiHistory('REGION', code)
  const heatDistricts = useLevelKpiHistory('DISTRICT', code)

  const settled = useMemo(() => settledWeeks(weeks), [weeks])
  const rows = useMemo(() => (ready ? boardRows(all, weeks, week) : week === latest ? summaryRows(manifest) : new Map<KpiCode, BoardRow>()), [ready, all, weeks, week, latest, manifest])
  const headline = useMemo(() => (ready ? nodeHeadline(all, week, lead) : null), [ready, all, week, lead])
  const series = useMemo(() => {
    const byWeek = new Map(all.filter((r) => r.kpi_code === code).map((r) => [r.iso_week_id, r]))
    return weeks.map((w) => byWeek.get(w))
  }, [all, code, weeks])
  // The 12-month measure has no value before a year of history: the chart starts at its first
  // value (or at the chosen week, if that is earlier) instead of drawing a year of nothing.
  const start = useMemo(() => {
    const first = series.findIndex((r) => r?.value != null)
    return first < 0 ? 0 : Math.min(first, Math.max(0, weeks.indexOf(week)))
  }, [series, weeks, week])
  const plotWeeks = weeks.slice(start)
  const plotted = series.slice(start)
  const current = series[weeks.indexOf(week)]
  const better = code === 'AVG_MEET_MIN' ? 'neither' : LOWER_IS_BETTER.has(code) ? 'lower' : 'higher'
  const multipleWeeks = weeks.slice(Math.max(0, weeks.indexOf(week) - MULTIPLE_WEEKS + 1), weeks.indexOf(week) + 1)
  const funnel = funnelFor(org.status === 'ready' ? org.data[0] : undefined, all, week, settled.has(week))
  const drill = (id: string) => `/r/${encodeURIComponent(id)}${week === latest ? '' : `?week=${encodeURIComponent(week)}`}`
  const flagged = series.filter((r) => r?.flag === 'ANOMALY').length
  const recap = useRecap()
  const wide = useMedia('(min-width: 64rem)')
  const phone = useMedia('(max-width: 40rem)')

  return <>
    <header className="briefing-head">
      <div className="briefing-when">
        <p><span className="briefing-week">Week {week.slice(6)}</span> {weekSpan(week)}</p>
        <WeekStepper weeks={weeks} week={week} latest={latest} onWeek={(w) => set('week', w)} />
      </div>
      <h1 className="briefing-headline">{headline?.title ?? `The weekly report for ${week}`}</h1>
      <p className="briefing-support">{headline ? [headline.record, headline.support].filter(Boolean).join(' ') : history.status === 'loading' ? 'Reading two years of weekly runs…' : 'Maplecrest Bank (fictional), national figures.'}</p>
    </header>

    <RunStatusBanner manifest={manifest} />

    <section className="hero" aria-labelledby="hero-title">
      <div className="hero-head briefing-hero-head">
        <div>
          <h2 id="hero-title" className="hero-title">
            <Explain card={{ title: KPI_LABELS[code], what: KPI_PLAIN[code], answer: { q: 'How is it counted?', a: KPI_DEFINITIONS[code] } }}>
              {(described) => <span className="term" tabIndex={0} {...described}>{KPI_LABELS[code]}</span>}
            </Explain>
          </h2>
          <p className="hero-definition">{KPI_PLAIN[code]}</p>
        </div>
        <p className="hero-now">
          <span className="hero-value figure-num">{formatKpi(code, current?.value ?? rows.get(code)?.value)}</span>
          <Delta value={current?.wow_pct ?? rows.get(code)?.wow} better={better} />
        </p>
      </div>
      <div className="briefing-hero-plot">
      {history.status === 'error' && <DataNotice what="the weekly history" onRetry={history.retry} />}
      <TrendChart weeks={plotWeeks} values={plotted.map((r) => r?.value ?? null)} usual={plotted.map((r) => (r && settled.has(r.iso_week_id) ? r.trailing_13w_avg ?? null : null))}
        flagged={plotted.map((r) => r?.flag === 'ANOMALY')} selected={week} onSelect={(w) => set('week', w)} morphKey={code} fitFrom={Math.max(0, WARM_UP_WEEKS - start)}
        format={(v) => formatKpi(code, v)} height={heroChartHeight(wide, phone)} hint="Click to open this week"
        describe={(i) => {
          const r = plotted[i]
          return r ? happened({ code, value: r.value, wow: r.wow_pct, usual: settled.has(r.iso_week_id) ? r.trailing_13w_avg ?? null : null, flag: r.flag === 'ANOMALY', better }) : []
        }}
        label={`${KPI_LABELS[code]}, national, ${plotWeeks[0]} to ${plotWeeks.at(-1)}; ${flagged} anomaly weeks. Use the arrow keys to choose a week.`} />
      <p className="hero-legend">
        <span><i className="hero-key-line" aria-hidden="true" />Weekly value</span>
        <span><i className="hero-key-usual" aria-hidden="true" /><Term {...TERMS.usual} /></span>
        <span><i className="hero-key-flag" aria-hidden="true" /><Term {...TERMS.anomaly} /></span>
        <SeriesCsvButton rows={series} filename={`advisor-pulse_CA_${code}.csv`} />
      </p>
      <details className="figure-table hero-table">
        <summary>Show the numbers</summary>
        <div className="hero-table-scroll" tabIndex={0} role="region" aria-label={`${KPI_LABELS[code]} by week`}>
          <table><thead><tr><th scope="col">Week</th><th scope="col" className="num">Value</th><th scope="col" className="num">Usual</th><th scope="col" className="num">WoW</th><th scope="col">Flag</th></tr></thead>
            <tbody>{[...series].reverse().map((r) => r && <tr key={r.iso_week_id} aria-current={r.iso_week_id === week ? 'true' : undefined}>
              <th scope="row">{r.iso_week_id}</th><td className="num">{formatKpi(code, r.value)}</td>
              <td className="num">{settled.has(r.iso_week_id) ? formatKpi(code, r.trailing_13w_avg) : '–'}</td>
              <td className="num">{formatWow(r.wow_pct).replace(' WoW', '')}</td><td>{r.flag === 'ANOMALY' ? 'Anomaly' : ''}</td>
            </tr>)}</tbody></table>
        </div>
      </details>
      </div>
    </section>

    {/* The next answer sits right under the chart, on the first screen: every measure, the lead KPI first. */}
    <section className="measures" aria-labelledby="measures-title">
      <header className="measures-head">
        <h2 id="measures-title">Every measure</h2>
        <p className="section-lede">Hover or focus a measure for what it means; click to plot it.</p>
      </header>
      <KpiBoard rows={rows} selected={code} onSelect={(c) => set('kpi', c)} />
    </section>

    {/* The week in depth, for the measure plotted above. */}
    <div className="briefing-depth">

    {recap?.week === week && <Section id="recap" title="The week in 20 seconds" lede="A short video the weekly run renders from the same numbers.">
      <WeekRecap recap={recap} />
    </Section>}

    <QuarterPanel nodeId="CA" nodeName="Canada" code={code} better={better} childLabel="Regions" hrefFor={(id) => `/r/${encodeURIComponent(id)}`} />

    {funnel && <Section id="funnel" title="From call to conversion" lede="This week, step by step.">
      <Funnel data={funnel} />
    </Section>}

    {NATIONAL_ONLY.has(code) && <Section id="regions" title="By region and week" lede="">
      <p className="national-only">{KPI_LABELS[code]} is measured on the whole weekly batch, before rows are attributed to a branch, so it has no regional split. Choose a business measure above to compare regions.</p>
    </Section>}

    {!NATIONAL_ONLY.has(code) && regions.status === 'ready' && <Section id="moved" title="What moved" lede="Each region against its own usual week.">
      <WhatMoved regions={regions.data} code={code} week={week} better={better} settled={settled.has(week)} hrefFor={drill} />
    </Section>}

    {!NATIONAL_ONLY.has(code) && <Section id="regions" title="By region" lede={<>Last {multipleWeeks.length} weeks; the dashed line is <Term {...TERMS.national}>Canada</Term>.</>}>
      {regions.status === 'ready' && history.status === 'ready' && <RegionMultiples regions={regions.data} national={all} code={code} week={week} weeks={multipleWeeks} settled={settled.has(week)} hrefFor={drill} />}
      {regions.status === 'loading' && <p aria-busy="true">Loading the regions…</p>}
      {regions.status === 'error' && <DataNotice what="the regional figures" onRetry={regions.retry} />}
    </Section>}

    {!NATIONAL_ONLY.has(code) && <Section id="weeks" title="Every week at a glance" lede={<>One cell per area and week: <span className="swatch-word swatch-better">{better === 'neither' ? 'longer' : 'better'}</span> or <span className="swatch-word swatch-worse">{better === 'neither' ? 'shorter' : 'worse'}</span> than its <Term {...TERMS.usual}>usual</Term>.</>}>
      {heatRegions.status === 'ready' && heatDistricts.status === 'ready' && <WeekHeatmap regions={heatRegions.data} districts={heatDistricts.data} code={code} weeks={weeks} week={week} onSelect={(w) => set('week', w)} />}
      {(heatRegions.status === 'loading' || heatDistricts.status === 'loading') && <p aria-busy="true">Loading every week…</p>}
      {heatRegions.status === 'error' && <DataNotice what="the week-by-week view" onRetry={heatRegions.retry} />}
    </Section>}


    </div>

    <p className="briefing-more"><Link to="/map">See the week on the map</Link></p>
  </>
}

/** The national weekly briefing. KPI values from the manifest summary paint before DuckDB-WASM loads. */
export function Overview() {
  const data = usePulseData()
  const manifest = useManifest()
  useEffect(() => {
    if (manifest.status !== 'ready') return
    const idle = window.requestIdleCallback ?? ((run: () => void) => window.setTimeout(run, 1))
    idle(() => data.warm())
  }, [data, manifest.status])

  return <main className="briefing">
    {manifest.status === 'loading' && <p className="intro" aria-busy="true">Loading the latest weekly report…</p>}
    {manifest.status === 'error' && <><h1>Overview</h1><DataNotice what="this week's report" onRetry={manifest.retry} /></>}
    {manifest.status === 'ready' && <Briefing manifest={manifest.data} />}
  </main>
}
