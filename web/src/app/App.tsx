import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Link, NavLink, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { DataNotice, useManifest } from '../data'
import { AdvisorLeaderboard, OrgLeaderboard } from '../features/leaderboard/Leaderboard'
import { NarrativePanel } from '../features/narrative/NarrativePanel'
import { Overview } from './Overview'
import { useReducedMotion } from './useReducedMotion'

// Dev-only reference page for the design system; tree-shaken out of production builds.
const KitchenSink = import.meta.env.DEV ? lazy(() => import('../components/primitives/KitchenSink')) : null

const navigation = [
  ['/', 'Overview'], ['/map', 'Map'], ['/pipeline', 'Pipeline'],
  ['/quality', 'Data quality'], ['/case-study', 'Case study'],
] as const

function Page({ title }: { title: string }) {
  return <main><p className="eyebrow">Maplecrest Bank · fictional</p><h1>{title}</h1><p className="intro">A weekly view of advisor activity, report quality, and pipeline status.</p></main>
}

function DrillPage({ title }: { title: string }) {
  const { region, district, branch, advisor } = useParams()
  const manifest = useManifest()
  const levels = [region, district, branch, advisor].filter(Boolean)
  const nodeId = advisor ?? branch ?? district ?? region
  const { pathname } = useLocation()
  // The next drill segment under this node: districts, then branches, then advisors.
  const child = advisor ? null : branch ? 'a' : district ? 'b' : 'd'
  const childHref = (id: string) => `${pathname.replace(/\/$/, '')}/${child}/${encodeURIComponent(id)}`
  return <main>
    <p className="eyebrow">Maplecrest Bank · fictional</p>
    <h1>{title}</h1>
    <p className="intro">Weekly advisor activity for {nodeId}.</p>
    <nav className="drill-trail" aria-label="Drill path">{levels.map((level, index) => <span key={index}>{index > 0 && ' / '}{level}</span>)}</nav>
    {manifest.status === 'loading' && <p aria-busy="true">Loading the latest weekly report…</p>}
    {manifest.status === 'error' && <DataNotice what="this week's report" onRetry={manifest.retry} />}
    {manifest.status === 'ready' && nodeId && <NarrativePanel week={manifest.data.latest_week} nodeId={nodeId} />}
    {manifest.status === 'ready' && nodeId && child === 'a' && <AdvisorLeaderboard weeks={manifest.data.weeks_available} parentId={nodeId} parentName={nodeId} childHref={childHref} />}
    {manifest.status === 'ready' && nodeId && child && child !== 'a' && <OrgLeaderboard weeks={manifest.data.weeks_available} parentId={nodeId} parentName={nodeId} childHref={childHref} />}
  </main>
}

function Shell() {
  const reducedMotion = useReducedMotion()
  useEffect(() => { document.documentElement.dataset.motion = reducedMotion ? 'reduced' : 'full' }, [reducedMotion])
  return <div className="site">
    <header className="site-header"><Link className="brand" to="/">Advisor Pulse</Link><nav className="site-nav" aria-label="Main navigation">{navigation.slice(1).map(([path, label]) => <NavLink key={path} to={path}>{label}</NavLink>)}</nav></header>
    <Routes>
      <Route path="/" element={<Overview />} />
      <Route path="/r/:region" element={<DrillPage title="Region" />} />
      <Route path="/r/:region/d/:district" element={<DrillPage title="District" />} />
      <Route path="/r/:region/d/:district/b/:branch" element={<DrillPage title="Branch" />} />
      <Route path="/r/:region/d/:district/b/:branch/a/:advisor" element={<DrillPage title="Advisor" />} />
      <Route path="/map" element={<Page title="Map" />} />
      <Route path="/pipeline" element={<Page title="Pipeline" />} />
      <Route path="/quality" element={<Page title="Data quality" />} />
      <Route path="/case-study" element={<Page title="Case study" />} />
      {KitchenSink && <Route path="/_kitchen-sink" element={<Suspense fallback={null}><KitchenSink /></Suspense>} />}
      <Route path="*" element={<Page title="Page not found" />} />
    </Routes>
    <footer className="site-footer">Weekly batch report · synthetic data · fictional bank</footer>
  </div>
}

export function App() { return <BrowserRouter><Shell /></BrowserRouter> }
