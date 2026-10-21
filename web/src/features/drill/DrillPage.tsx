import { useMemo, useRef } from 'react'
import { TrendChart } from '../../components/charts/TrendChart'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useReducedMotion } from '../../app/useReducedMotion'
import { Breadcrumb, Delta, Section, SeriesCsvButton, Stat, StatGroup, WeekStepper } from '../../components/primitives'
import { DataNotice, KPI_LABELS, formatKpi, useAdvisorWeekly, useChildReportHistory, useManifest, useNodeNames, useWeeklyReportHistory } from '../../data'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'
import { WARM_UP_WEEKS, settledWeeks } from '../../data/usual'
import { AnimatedKpiValue } from '../../motion/AnimatedKpiValue'
import { AdvisorLeaderboard, OrgLeaderboard } from '../leaderboard/Leaderboard'
import { ADVISOR_KPIS, ORG_KPIS, advisorValue } from '../leaderboard/rows'
import { NarrativePanel } from '../narrative/NarrativePanel'
import { KPI_DEFINITIONS, LOWER_IS_BETTER } from '../overview/kpis'
import { KpiBoard, boardRows } from '../overview/KpiBoard'
import { weekHeadline } from '../overview/headline'
import { ChildMultiples } from './ChildMultiples'
import { type DrillPath, LEVEL_LABEL, crumbs, drillPath, resolveWeek, weekQuery } from './path'
import { navigateWithTransition } from './transition'
import './drill.css'
import { QuarterPanel } from '../quarters/QuarterPanel'

interface Tile { code: KpiCode; value: number | null; wow: number | null; anomaly: boolean }

/** For one advisor, "per advisor" is just their own count. */
const advisorLabel = (code: KpiCode) => (code === 'ACT_PER_ADV' ? 'Activities completed' : KPI_LABELS[code])

function better(code: KpiCode) {
  return code === 'AVG_MEET_MIN' ? 'neither' : LOWER_IS_BETTER.has(code) ? 'lower' : 'higher'
}

function Tiles({ tiles, label, name = (code: KpiCode) => KPI_LABELS[code] }: { tiles: Tile[]; label: string; name?: (code: KpiCode) => string }) {
  return <StatGroup label={label}>
    {tiles.map((t, index) => <Stat key={t.code} data-kpi={t.code} label={name(t.code)} value={<AnimatedKpiValue code={t.code} value={t.value} />} emphasis={index === 0}>
      <Delta value={t.wow} better={better(t.code)} />
      {t.wow != null && <span> WoW</span>}
      {t.anomaly && <span className="kpi-anomaly">Anomaly</span>}
    </Stat>)}
  </StatGroup>
}

/** Keep the prior tiles mounted during a week fetch so values can tween when it completes. */
function PendingTiles({ tiles, label, loading, name }: { tiles: Tile[]; label: string; loading: boolean; name?: (code: KpiCode) => string }) {
  return <div aria-busy={loading}>
    {loading && <span className="motion-sr-only" role="status">Updating KPIs…</span>}
    <div style={{ visibility: loading ? 'hidden' : 'visible' }}><Tiles tiles={tiles} label={label} name={name} /></div>
  </div>
}

const CHILD_WEEKS = 26
const CHILD_LABEL = { d: 'Districts', b: 'Branches', a: 'Advisors' } as const

/**
 * An org node's week: its sentence, one measure across every weekly run over its parent's
 * line, every measure, and its children as small multiples on one axis.
 */
function OrgReport({ path, week, weeks, name, parentName, setKpi, code, childHref, onChildClick }: {
  path: DrillPath
  week: string
  weeks: readonly string[]
  name: string
  parentName: string
  code: KpiCode
  setKpi: (code: KpiCode) => void
  childHref: (id: string) => string
  onChildClick: (event: React.MouseEvent<HTMLAnchorElement>, href: string) => void
}) {
  const parentId = path.orgIds.length > 1 ? path.orgIds.at(-2)! : 'CA'
  const history = useWeeklyReportHistory(path.nodeId, weeks)
  const parent = useWeeklyReportHistory(parentId, weeks)
  const childWeeks = weeks.slice(Math.max(0, weeks.indexOf(week) - CHILD_WEEKS + 1), weeks.indexOf(week) + 1)
  const children = useChildReportHistory(path.childSegment && path.childSegment !== 'a' ? path.nodeId : '', path.childSegment && path.childSegment !== 'a' ? childWeeks : [])
  const all = useMemo<WeeklyReport[]>(() => (history.status === 'ready' ? history.data : []), [history])
  const parentRows = useMemo<WeeklyReport[]>(() => (parent.status === 'ready' ? parent.data : []), [parent])
  const settled = useMemo(() => settledWeeks(weeks), [weeks])
  const rows = useMemo(() => boardRows(all, weeks, week), [all, weeks, week])
  const series = useMemo(() => {
    const byWeek = new Map(all.filter((r) => r.kpi_code === code).map((r) => [r.iso_week_id, r]))
    return weeks.map((w) => byWeek.get(w))
  }, [all, code, weeks])
  const parentLine = useMemo(() => {
    const byWeek = new Map(parentRows.filter((r) => r.kpi_code === code).map((r) => [r.iso_week_id, r.value ?? null]))
    return weeks.map((w) => byWeek.get(w) ?? null)
  }, [parentRows, code, weeks])
  const current = series[weeks.indexOf(week)]
  // The narrative panel below carries the model's headline; the lede stays the computed one.
  const lede = weekHeadline(all, week)?.lead
  const better = code === 'AVG_MEET_MIN' ? 'neither' : LOWER_IS_BETTER.has(code) ? 'lower' : 'higher'
  const childLabel = path.childSegment ? CHILD_LABEL[path.childSegment] : null

  if (history.status === 'error') return <DataNotice what="these KPIs" onRetry={history.retry} />
  if (history.status === 'empty') return <p>No KPIs were reported for {name}.</p>
  return <>
    <p className="drill-lede" aria-live="polite">{lede ?? (history.status === 'loading' ? 'Reading the weekly runs…' : '')}</p>
    <section className="hero" aria-labelledby="drill-hero-title">
      <div className="hero-head">
        <div>
          <h2 id="drill-hero-title" className="hero-title">{KPI_LABELS[code]}</h2>
          <p className="hero-definition">{KPI_DEFINITIONS[code]}</p>
        </div>
        <p className="hero-now">
          <span className="hero-value figure-num">{formatKpi(code, current?.value)}</span>
          <Delta value={current?.wow_pct} better={better} />
        </p>
      </div>
      <TrendChart weeks={weeks} values={series.map((r) => r?.value ?? null)} reference={parentLine}
        usual={series.map((r) => (r && settled.has(r.iso_week_id) ? r.trailing_13w_avg ?? null : null))}
        flagged={series.map((r) => r?.flag === 'ANOMALY')} selected={week} morphKey={code} fitFrom={WARM_UP_WEEKS} height={260}
        format={(v) => formatKpi(code, v)} label={`${KPI_LABELS[code]}, ${name}, ${weeks[0]} to ${weeks.at(-1)}, with ${parentName} dashed`} />
      <p className="hero-legend">
        <span><i className="hero-key-line" aria-hidden="true" />{name}</span>
        <span><i className="hero-key-ref" aria-hidden="true" />{parentName}</span>
        <span><i className="hero-key-usual" aria-hidden="true" />Usual: trailing 13-week average</span>
        <span><i className="hero-key-flag" aria-hidden="true" />Anomaly</span>
        <span className="hero-hint"><SeriesCsvButton rows={series} filename={`advisor-pulse_${path.nodeId}_${code}.csv`} /></span>
      </p>
    </section>
    <Section id="kpis" title={`${name}, week ${week}`} lede="Change is against the prior week. Choose a measure to plot it above." revealOrder={0}>
      {history.status === 'loading' && !rows.size ? <p aria-busy="true">Loading the KPIs…</p> : <KpiBoard rows={rows} selected={code} onSelect={setKpi} only={ORG_KPIS} />}
    </Section>
    {childLabel && path.childSegment !== 'a' && <Section id="children" title={`${childLabel} in ${name}`} lede={`${KPI_LABELS[code]}, last ${childWeeks.length} weeks, best first. The dashed line is ${name}.`}>
      {children.status === 'loading' && <p aria-busy="true">Loading the {childLabel.toLowerCase()}…</p>}
      {children.status === 'error' && <DataNotice what={`the ${childLabel.toLowerCase()}`} onRetry={children.retry} />}
      {children.status === 'ready' && <ChildMultiples rows={children.data} parent={childWeeks.map((w) => parentLineFor(all, code, w))} code={code} week={week} weeks={childWeeks} hrefFor={childHref} onOpen={onChildClick} />}
    </Section>}
    <QuarterPanel nodeId={path.nodeId} nodeName={name} code={code} better={better}
      childLabel={childLabel && path.childSegment !== 'a' ? childLabel : undefined} hrefFor={childHref} onOpen={onChildClick} />
  </>
}

function parentLineFor(rows: readonly WeeklyReport[], code: KpiCode, week: string): number | null {
  return rows.find((r) => r.kpi_code === code && r.iso_week_id === week)?.value ?? null
}

function AdvisorKpis({ weeks, branchId, advisorId, code, setKpi }: { weeks: readonly string[]; branchId: string; advisorId: string; code: KpiCode; setKpi: (code: KpiCode) => void }) {
  const recent = weeks.slice(-CHILD_WEEKS)
  const result = useAdvisorWeekly(branchId, recent)
  const last = useRef<{ advisorId: string; tiles: Tile[] } | null>(null)
  const chosen: KpiCode = ADVISOR_KPIS.includes(code) ? code : 'ACT_PER_ADV'
  if (result.status === 'error') return <DataNotice what="these KPIs" onRetry={result.retry} />
  if (result.status === 'loading' && last.current?.advisorId === advisorId) {
    return <PendingTiles tiles={last.current.tiles} label={`${advisorId} key performance indicators`} loading name={advisorLabel} />
  }
  if (result.status === 'loading') return <p aria-busy="true">Loading the KPIs…</p>
  const rows = result.status === 'ready' ? result.data.filter((r) => r.advisor_id === advisorId) : []
  const current = rows.find((r) => r.iso_week_id === recent.at(-1))
  if (!current) return <p>{advisorId} has no activity recorded at this branch in {recent.at(-1)}.</p>
  const prior = rows.find((r) => r.iso_week_id === recent.at(-2) && recent.length > 1)
  const tiles = ADVISOR_KPIS.map((kpi) => {
    const value = advisorValue(kpi, current)
    const before = prior ? advisorValue(kpi, prior) : null
    const wow = value !== null && before ? Math.round(((value - before) / before) * 10000) / 10000 : null
    return { code: kpi, value, wow, anomaly: false }
  })
  last.current = { advisorId, tiles }
  // The branch's other advisors, as a median line, so one advisor is read against their peers.
  const byWeek = (w: string) => rows.find((r) => r.iso_week_id === w)
  const peers = recent.map((w) => {
    const values = (result.status === 'ready' ? result.data : []).filter((r) => r.iso_week_id === w && r.advisor_id !== advisorId)
      .map((r) => advisorValue(chosen, r)).filter((v): v is number => v !== null).sort((a, b) => a - b)
    return values.length ? values[Math.floor((values.length - 1) / 2)]! : null
  })
  return <>
    <PendingTiles tiles={tiles} label={`${advisorId} key performance indicators`} loading={false} name={advisorLabel} />
    <figure className="advisor-trend">
      <label className="advisor-pick">Plot <select value={chosen} onChange={(event) => setKpi(event.target.value as KpiCode)}>
        {ADVISOR_KPIS.map((kpi) => <option key={kpi} value={kpi}>{advisorLabel(kpi)}</option>)}
      </select></label>
      <TrendChart weeks={recent} values={recent.map((w) => { const r = byWeek(w); return r ? advisorValue(chosen, r) : null })} reference={peers}
        selected={recent.at(-1)} morphKey={chosen} height={200} format={(v) => formatKpi(chosen, v)}
        label={`${advisorLabel(chosen)} for ${advisorId} over ${recent.length} weeks, with the branch's median advisor dashed`} />
      <figcaption className="hero-legend"><span><i className="hero-key-line" aria-hidden="true" />{advisorId}</span><span><i className="hero-key-ref" aria-hidden="true" />Median of the branch's other advisors</span></figcaption>
    </figure>
  </>
}

function Drill({ path, weeks, latest }: { path: DrillPath; weeks: readonly string[]; latest: string }) {
  const [search, setSearch] = useSearchParams()
  const navigate = useNavigate()
  const reducedMotion = useReducedMotion()
  const week = resolveWeek(search.get('week'), weeks)!
  const shown = weeks.slice(0, weeks.indexOf(week) + 1)
  const query = weekQuery(week, latest)
  const names = useNodeNames(path.orgIds)
  const nameMap = names.status === 'ready' ? names.data : new Map<string, string>()
  const name = nameMap.get(path.nodeId) ?? path.nodeId
  const requested = search.get('kpi') as KpiCode | null
  const code: KpiCode = requested && ORG_KPIS.includes(requested) ? requested : 'ACT_PER_ADV'
  const parentName = path.orgIds.length > 1 ? nameMap.get(path.orgIds.at(-2)!) ?? path.orgIds.at(-2)! : 'Canada'
  const set = (key: 'week' | 'kpi', value: string) => {
    const next = new URLSearchParams(search)
    if (value === (key === 'week' ? latest : 'ACT_PER_ADV')) next.delete(key)
    else next.set(key, value)
    setSearch(next)
  }
  const childQuery = code === 'ACT_PER_ADV' || path.childSegment === 'a' ? query : `${query ? `${query}&` : '?'}kpi=${code}`
  const childHref = (id: string) => `${path.hrefs.at(-1)}/${path.childSegment}/${encodeURIComponent(id)}${childQuery}`
  const onChildClick = (event: React.MouseEvent<HTMLAnchorElement>, href: string) => navigateWithTransition(event, href, navigate, reducedMotion)

  return <>
    <Breadcrumb items={crumbs(path, nameMap, query)} />
    <p className="drill-level">{LEVEL_LABEL[path.level]}</p>
    <h1 className="drill-title">{name}</h1>
    <div className="drill-when"><WeekStepper weeks={weeks} week={week} latest={latest} onWeek={(w) => set('week', w)} /></div>
    {path.level === 'ADVISOR'
      ? <Section id="kpis" title={`${name}, week ${week}`} lede="Change is against the prior week." revealOrder={0}>
        <AdvisorKpis weeks={shown} branchId={path.orgIds[2]!} advisorId={path.nodeId} code={code} setKpi={(c) => set('kpi', c)} />
      </Section>
      : <OrgReport path={path} week={week} weeks={weeks} name={name} parentName={parentName} code={code} setKpi={(c) => set('kpi', c)} childHref={childHref} onChildClick={onChildClick} />}
    {path.level !== 'ADVISOR' && <NarrativePanel week={week} nodeId={path.nodeId} />}
    {path.childSegment === 'a' && <AdvisorLeaderboard weeks={shown} parentId={path.nodeId} parentName={name} childHref={childHref} onChildClick={onChildClick} />}
    {(path.childSegment === 'd' || path.childSegment === 'b') && <OrgLeaderboard weeks={shown} parentId={path.nodeId} parentName={name} childHref={childHref} onChildClick={onChildClick} />}
  </>
}

/** /r/:region[/d/:district[/b/:branch[/a/:advisor]]], with the week in `?week=`. */
export function DrillPage() {
  const params = useParams()
  const path = useMemo(() => drillPath(params), [params])
  const manifest = useManifest()
  if (!path) return null
  return <main className="drill">
    {manifest.status === 'loading' && <><h1>{path.nodeId}</h1><p aria-busy="true">Loading the latest weekly report…</p></>}
    {manifest.status === 'error' && <><h1>{path.nodeId}</h1><DataNotice what="this week's report" onRetry={manifest.retry} /></>}
    {manifest.status === 'ready' && <Drill path={path} weeks={manifest.data.weeks_available} latest={manifest.data.latest_week} />}
  </main>
}
