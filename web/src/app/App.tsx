import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Link, NavLink, Route, Routes } from 'react-router-dom'
import { DrillPage } from '../features/drill/DrillPage'
import { Overview } from './Overview'
import { useReducedMotion } from './useReducedMotion'

// React Flow loads only with the pipeline page.
const PipelinePage = lazy(() => import('../features/pipeline/PipelinePage').then((m) => ({ default: m.PipelinePage })))
const MapPage = lazy(() => import('../features/map/MapPage').then((m) => ({ default: m.MapPage })))
// Dev-only reference page for the design system; tree-shaken out of production builds.
const KitchenSink = import.meta.env.DEV ? lazy(() => import('../components/primitives/KitchenSink')) : null

const navigation = [
  ['/', 'Overview'], ['/map', 'Map'], ['/pipeline', 'Pipeline'],
  ['/quality', 'Data quality'], ['/case-study', 'Case study'],
] as const

function Page({ title }: { title: string }) {
  return <main><p className="eyebrow">Maplecrest Bank · fictional</p><h1>{title}</h1><p className="intro">A weekly view of advisor activity, report quality, and pipeline status.</p></main>
}

function Shell() {
  const reducedMotion = useReducedMotion()
  useEffect(() => { document.documentElement.dataset.motion = reducedMotion ? 'reduced' : 'full' }, [reducedMotion])
  return <div className="site">
    <header className="site-header"><Link className="brand" to="/">Advisor Pulse</Link><nav className="site-nav" aria-label="Main navigation">{navigation.slice(1).map(([path, label]) => <NavLink key={path} to={path}>{label}</NavLink>)}</nav></header>
    <Routes>
      <Route path="/" element={<Overview />} />
      <Route path="/r/:region" element={<DrillPage />} />
      <Route path="/r/:region/d/:district" element={<DrillPage />} />
      <Route path="/r/:region/d/:district/b/:branch" element={<DrillPage />} />
      <Route path="/r/:region/d/:district/b/:branch/a/:advisor" element={<DrillPage />} />
      <Route path="/map" element={<Suspense fallback={<main aria-busy="true" />}><MapPage /></Suspense>} />
      <Route path="/pipeline" element={<Suspense fallback={<main aria-busy="true" />}><PipelinePage /></Suspense>} />
      <Route path="/quality" element={<Page title="Data quality" />} />
      <Route path="/case-study" element={<Page title="Case study" />} />
      {KitchenSink && <Route path="/_kitchen-sink" element={<Suspense fallback={null}><KitchenSink /></Suspense>} />}
      <Route path="*" element={<Page title="Page not found" />} />
    </Routes>
    <footer className="site-footer">Weekly batch report · synthetic data · fictional bank</footer>
  </div>
}

export function App() { return <BrowserRouter><Shell /></BrowserRouter> }
