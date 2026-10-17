import { useMemo, useRef } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useReducedMotion } from '../../app/useReducedMotion'
import { Breadcrumb, Delta, Section, Stat, StatGroup } from '../../components/primitives'
import { DataNotice, KPI_LABELS, useAdvisorWeekly, useManifest, useNodeNames, useWeeklyReport } from '../../data'
import type { KpiCode } from '../../data/generated/weekly_report'
import { AnimatedKpiValue } from '../../motion/AnimatedKpiValue'
import { AdvisorLeaderboard, OrgLeaderboard } from '../leaderboard/Leaderboard'
import { ADVISOR_KPIS, ORG_KPIS, advisorValue } from '../leaderboard/rows'
import { NarrativePanel } from '../narrative/NarrativePanel'
import { LOWER_IS_BETTER } from '../overview/kpis'
import { type DrillPath, LEVEL_LABEL, crumbs, drillPath, resolveWeek, weekQuery } from './path'
import { navigateWithTransition } from './transition'
import './drill.css'

interface Tile { code: KpiCode; value: number | null; wow: number | null; anomaly: boolean }

function better(code: KpiCode) {
  return code === 'AVG_MEET_MIN' ? 'neither' : LOWER_IS_BETTER.has(code) ? 'lower' : 'higher'
}

function Tiles({ tiles, label }: { tiles: Tile[]; label: string }) {
  return <StatGroup label={label}>
    {tiles.map((t, index) => <Stat key={t.code} data-kpi={t.code} label={KPI_LABELS[t.code]} value={<AnimatedKpiValue code={t.code} value={t.value} />} emphasis={index === 0}>
      <Delta value={t.wow} better={better(t.code)} />
      {t.wow != null && <span> WoW</span>}
      {t.anomaly && <span className="kpi-anomaly">Anomaly</span>}
    </Stat>)}
  </StatGroup>
}

/** Keep the prior tiles mounted during a week fetch so values can tween when it completes. */
function PendingTiles({ tiles, label, loading }: { tiles: Tile[]; label: string; loading: boolean }) {
  return <div aria-busy={loading}>
    {loading && <span role="status">Updating KPIs…</span>}
    <div style={{ visibility: loading ? 'hidden' : 'visible' }}><Tiles tiles={tiles} label={label} /></div>
  </div>
}

function OrgKpis({ week, nodeId, name }: { week: string; nodeId: string; name: string }) {
  const report = useWeeklyReport(week, { nodeId })
  const last = useRef<{ nodeId: string; tiles: Tile[] } | null>(null)
  if (report.status === 'error') return <DataNotice what="these KPIs" onRetry={report.retry} />
  if (report.status === 'empty') return <p>No KPIs were reported for {name} in {week}.</p>
  if (report.status === 'ready') {
    const byCode = new Map(report.data.map((r) => [r.kpi_code, r]))
    last.current = { nodeId, tiles: ORG_KPIS.filter((code) => byCode.has(code)).map((code) => {
      const row = byCode.get(code)!
      return { code, value: row.value ?? null, wow: row.wow_pct ?? null, anomaly: row.flag === 'ANOMALY' }
    }) }
  }
  const tiles = last.current?.nodeId === nodeId ? last.current.tiles : null
  if (!tiles) return <p aria-busy="true">Loading the KPIs…</p>
  return <PendingTiles tiles={tiles} label={`${name} key performance indicators`} loading={report.status === 'loading'} />
}

function AdvisorKpis({ weeks, branchId, advisorId }: { weeks: readonly string[]; branchId: string; advisorId: string }) {
  const recent = weeks.slice(-2)
  const result = useAdvisorWeekly(branchId, recent)
  const last = useRef<{ advisorId: string; tiles: Tile[] } | null>(null)
  if (result.status === 'error') return <DataNotice what="these KPIs" onRetry={result.retry} />
  if (result.status === 'loading' && last.current?.advisorId === advisorId) {
    return <PendingTiles tiles={last.current.tiles} label={`${advisorId} key performance indicators`} loading />
  }
  if (result.status === 'loading') return <p aria-busy="true">Loading the KPIs…</p>
  const rows = result.status === 'ready' ? result.data.filter((r) => r.advisor_id === advisorId) : []
  const current = rows.find((r) => r.iso_week_id === recent.at(-1))
  if (!current) return <p>{advisorId} has no activity recorded at this branch in {recent.at(-1)}.</p>
  const prior = rows.find((r) => r.iso_week_id === recent.at(-2) && recent.length > 1)
  const tiles = ADVISOR_KPIS.map((code) => {
    const value = advisorValue(code, current)
    const before = prior ? advisorValue(code, prior) : null
    const wow = value !== null && before ? Math.round(((value - before) / before) * 10000) / 10000 : null
    return { code, value, wow, anomaly: false }
  })
  last.current = { advisorId, tiles }
  return <PendingTiles tiles={tiles} label={`${advisorId} key performance indicators`} loading={false} />
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
  const childHref = (id: string) => `${path.hrefs.at(-1)}/${path.childSegment}/${encodeURIComponent(id)}${query}`
  const onChildClick = (event: React.MouseEvent<HTMLAnchorElement>, href: string) => navigateWithTransition(event, href, navigate, reducedMotion)

  return <>
    <Breadcrumb items={crumbs(path, nameMap, query)} />
    <p className="drill-level">{LEVEL_LABEL[path.level]}</p>
    <h1 className="drill-title">{name}</h1>
    <label className="drill-week">Week
      <select value={week} onChange={(event) => {
        const next = new URLSearchParams(search)
        if (event.target.value === latest) next.delete('week')
        else next.set('week', event.target.value)
        setSearch(next)
      }}>
        {[...weeks].reverse().map((w) => <option key={w} value={w}>{w}{w === latest ? ' (latest)' : ''}</option>)}
      </select>
    </label>
    <Section id="kpis" title={`${name}, week ${week}`} lede="Change is against the prior week." revealOrder={0}>
      {path.level === 'ADVISOR'
        ? <AdvisorKpis weeks={shown} branchId={path.orgIds[2]!} advisorId={path.nodeId} />
        : <OrgKpis week={week} nodeId={path.nodeId} name={name} />}
    </Section>
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
    <p className="eyebrow">Maplecrest Bank · fictional</p>
    {manifest.status === 'loading' && <><h1>{path.nodeId}</h1><p aria-busy="true">Loading the latest weekly report…</p></>}
    {manifest.status === 'error' && <><h1>{path.nodeId}</h1><DataNotice what="this week's report" onRetry={manifest.retry} /></>}
    {manifest.status === 'ready' && <Drill path={path} weeks={manifest.data.weeks_available} latest={manifest.data.latest_week} />}
  </main>
}
